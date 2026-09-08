"""Private, multi-profile Discord application-command adapter for Axelyn Forge."""

import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, FrozenSet, Mapping, Optional

import discord
from discord import app_commands

from .context_selection import DEFAULT_CONTEXT_SELECTION_MODEL
from .errors import DiscordBotBusyError, DiscordBotError, ForgeError
from .job_source import DEFAULT_WEB_SEARCH_MODEL, normalize_job_url
from .openai_provider import DEFAULT_OPENAI_MODEL
from .tailoring import TailoringResult, tailor_resume_with_openai

LOGGER = logging.getLogger(__name__)
DEFAULT_MAX_TXT_BYTES = 512 * 1024
MAX_PASTED_JD_LENGTH = 6000
PROFILE_MANIFEST_SCHEMA_VERSION = "1"
PROFILE_PATH_FIELDS = {
    "template": "template",
    "data": "data",
    "schema": "schema",
    "bindings": "bindings",
    "coverLetterTemplate": "cover_letter_template",
    "coverLetterData": "cover_letter_data",
    "coverLetterSchema": "cover_letter_schema",
    "coverLetterBindings": "cover_letter_bindings",
    "context": "context",
    "database": "database",
    "outputDir": "output_dir",
}
PROFILE_REQUIRED_FIELDS = frozenset(
    {
        "displayName",
        "filenamePrefix",
        "coverLetterPrefix",
        *PROFILE_PATH_FIELDS,
    }
)
PROFILE_ALLOWED_FIELDS = PROFILE_REQUIRED_FIELDS
_PASTED_TEXT_IGNORABLES = str.maketrans(
    {
        "\u00ad": None,  # Soft hyphen copied from wrapped web content.
        "\u200b": None,  # Zero-width space.
        "\u2060": None,  # Word joiner.
        "\ufeff": None,  # Byte-order mark / zero-width no-break space.
    }
)


def _required_text(environ: Mapping[str, str], name: str) -> str:
    value = environ.get(name, "").strip()
    if not value:
        raise DiscordBotError(f"Missing required environment variable: {name}")
    return value


def _positive_integer(value: str, name: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise DiscordBotError(f"{name} must be a positive integer") from exc
    if parsed <= 0:
        raise DiscordBotError(f"{name} must be a positive integer")
    return parsed


def _id_set(value: str, name: str) -> FrozenSet[int]:
    values = [item.strip() for item in value.split(",") if item.strip()]
    if not values:
        raise DiscordBotError(
            f"{name} must contain at least one Discord user ID; the bot defaults to deny"
        )
    return frozenset(_positive_integer(item, name) for item in values)


@dataclass(frozen=True)
class CandidateProfile:
    profile_id: str
    display_name: str
    template: Path = Path("templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx")
    data: Path = Path("data/profile.json")
    schema: Path = Path("schemas/profile.schema.json")
    bindings: Path = Path("bindings/software-engineer.json")
    cover_letter_template: Path = Path(
        "templates/Amin_Haiqal_Cover_Letter_SDT_Template.docx"
    )
    cover_letter_data: Path = Path("data/cover_letter.json")
    cover_letter_schema: Path = Path("schemas/cover-letter.schema.json")
    cover_letter_bindings: Path = Path("bindings/cover-letter.json")
    context: Path = Path("context")
    database: Path = Path("data/context.sqlite3")
    output_dir: Path = Path("output")
    filename_prefix: str = "Amin_Haiqal_Resume"
    cover_letter_prefix: str = "Amin_Haiqal_Cover_Letter"

    def prepare(self) -> None:
        assets = {
            "template": self.template,
            "resume data": self.data,
            "schema": self.schema,
            "bindings": self.bindings,
            "cover-letter template": self.cover_letter_template,
            "cover-letter data": self.cover_letter_data,
            "cover-letter schema": self.cover_letter_schema,
            "cover-letter bindings": self.cover_letter_bindings,
        }
        missing = [f"{label}: {path}" for label, path in assets.items() if not path.is_file()]
        if not self.context.exists():
            missing.append(f"context: {self.context}")
        if missing:
            raise DiscordBotError(
                f"Missing Forge runtime assets for profile '{self.profile_id}':\n- "
                + "\n- ".join(missing)
            )
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DiscordBotError(
                f"Could not prepare persistent directories for profile "
                f"'{self.profile_id}': {exc}"
            ) from exc


def _manifest_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DiscordBotError(
            f"Profile manifest field {field_name} must be a non-empty string"
        )
    return value.strip()


def _manifest_path(value: object, field_name: str, manifest: Path) -> Path:
    configured = Path(_manifest_text(value, field_name))
    if configured.is_absolute():
        return configured
    return manifest.parent / configured


def _load_profile_manifest(manifest: Path) -> Mapping[int, CandidateProfile]:
    try:
        raw = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscordBotError(f"Could not read Forge profile manifest {manifest}: {exc}") from exc
    if not isinstance(raw, dict):
        raise DiscordBotError("Forge profile manifest must be a JSON object")
    expected_top_level = {"schemaVersion", "profiles", "discordUsers"}
    unknown_top_level = sorted(set(raw) - expected_top_level)
    missing_top_level = sorted(expected_top_level - set(raw))
    if unknown_top_level or missing_top_level:
        details = []
        if missing_top_level:
            details.append("missing: " + ", ".join(missing_top_level))
        if unknown_top_level:
            details.append("unknown: " + ", ".join(unknown_top_level))
        raise DiscordBotError("Invalid Forge profile manifest fields (" + "; ".join(details) + ")")
    if raw["schemaVersion"] != PROFILE_MANIFEST_SCHEMA_VERSION:
        raise DiscordBotError(
            f"Unsupported Forge profile manifest schema version "
            f"{raw['schemaVersion']!r}; expected {PROFILE_MANIFEST_SCHEMA_VERSION!r}"
        )

    raw_profiles = raw["profiles"]
    if not isinstance(raw_profiles, dict) or not raw_profiles:
        raise DiscordBotError("Forge profile manifest profiles must be a non-empty object")
    profiles = {}
    for raw_profile_id, raw_profile in raw_profiles.items():
        profile_id = _manifest_text(raw_profile_id, "profiles.<id>")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", profile_id):
            raise DiscordBotError(
                f"Invalid Forge profile ID {profile_id!r}; use 1-64 letters, numbers, "
                "underscores, or hyphens"
            )
        if not isinstance(raw_profile, dict):
            raise DiscordBotError(f"Forge profile {profile_id!r} must be an object")
        missing_fields = sorted(PROFILE_REQUIRED_FIELDS - set(raw_profile))
        unknown_fields = sorted(set(raw_profile) - PROFILE_ALLOWED_FIELDS)
        if missing_fields or unknown_fields:
            details = []
            if missing_fields:
                details.append("missing: " + ", ".join(missing_fields))
            if unknown_fields:
                details.append("unknown: " + ", ".join(unknown_fields))
            raise DiscordBotError(
                f"Invalid fields for Forge profile {profile_id!r} ("
                + "; ".join(details)
                + ")"
            )
        path_values = {
            attribute: _manifest_path(
                raw_profile[field_name],
                f"profiles.{profile_id}.{field_name}",
                manifest,
            )
            for field_name, attribute in PROFILE_PATH_FIELDS.items()
        }
        profiles[profile_id] = CandidateProfile(
            profile_id=profile_id,
            display_name=_manifest_text(
                raw_profile["displayName"],
                f"profiles.{profile_id}.displayName",
            ),
            filename_prefix=_manifest_text(
                raw_profile["filenamePrefix"],
                f"profiles.{profile_id}.filenamePrefix",
            ),
            cover_letter_prefix=_manifest_text(
                raw_profile["coverLetterPrefix"],
                f"profiles.{profile_id}.coverLetterPrefix",
            ),
            **path_values,
        )

    raw_users = raw["discordUsers"]
    if not isinstance(raw_users, dict) or not raw_users:
        raise DiscordBotError("Forge profile manifest discordUsers must be a non-empty object")
    user_profiles = {}
    for raw_user_id, raw_profile_id in raw_users.items():
        user_id = _positive_integer(str(raw_user_id).strip(), "discordUsers user ID")
        if user_id in user_profiles:
            raise DiscordBotError(
                f"Forge profile manifest contains duplicate Discord user ID {user_id}"
            )
        profile_id = _manifest_text(
            raw_profile_id,
            f"discordUsers.{raw_user_id}",
        )
        if profile_id not in profiles:
            raise DiscordBotError(
                f"Discord user {user_id} references unknown Forge profile {profile_id!r}"
            )
        user_profiles[user_id] = profiles[profile_id]
    return user_profiles


def _legacy_profile(values: Mapping[str, str]) -> CandidateProfile:
    return CandidateProfile(
        profile_id="default",
        display_name=values.get(
            "FORGE_PROFILE_DISPLAY_NAME", "Muhammad Amin Haiqal"
        ).strip()
        or "Muhammad Amin Haiqal",
        template=Path(
            values.get(
                "FORGE_TEMPLATE",
                "templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx",
            )
        ),
        data=Path(values.get("FORGE_DATA", "data/profile.json")),
        schema=Path(values.get("FORGE_SCHEMA", "schemas/profile.schema.json")),
        bindings=Path(values.get("FORGE_BINDINGS", "bindings/software-engineer.json")),
        cover_letter_template=Path(
            values.get(
                "FORGE_COVER_LETTER_TEMPLATE",
                "templates/Amin_Haiqal_Cover_Letter_SDT_Template.docx",
            )
        ),
        cover_letter_data=Path(
            values.get("FORGE_COVER_LETTER_DATA", "data/cover_letter.json")
        ),
        cover_letter_schema=Path(
            values.get("FORGE_COVER_LETTER_SCHEMA", "schemas/cover-letter.schema.json")
        ),
        cover_letter_bindings=Path(
            values.get("FORGE_COVER_LETTER_BINDINGS", "bindings/cover-letter.json")
        ),
        context=Path(values.get("FORGE_CONTEXT", "context")),
        database=Path(values.get("FORGE_DATABASE", "data/context.sqlite3")),
        output_dir=Path(values.get("FORGE_OUTPUT_DIR", "output")),
        filename_prefix=values.get(
            "FORGE_FILENAME_PREFIX", "Amin_Haiqal_Resume"
        ).strip()
        or "Amin_Haiqal_Resume",
        cover_letter_prefix=values.get(
            "FORGE_COVER_LETTER_PREFIX", "Amin_Haiqal_Cover_Letter"
        ).strip()
        or "Amin_Haiqal_Cover_Letter",
    )


@dataclass(frozen=True)
class DiscordBotConfig:
    token: str = field(repr=False)
    user_profiles: Mapping[int, CandidateProfile] = field(repr=False)
    guild_id: Optional[int] = None
    model: str = DEFAULT_OPENAI_MODEL
    cover_letter_model: str = DEFAULT_OPENAI_MODEL
    context_model: str = DEFAULT_CONTEXT_SELECTION_MODEL
    web_model: str = DEFAULT_WEB_SEARCH_MODEL
    max_txt_bytes: int = DEFAULT_MAX_TXT_BYTES

    @classmethod
    def from_environ(
        cls,
        environ: Optional[Mapping[str, str]] = None,
    ) -> "DiscordBotConfig":
        values = os.environ if environ is None else environ
        token = _required_text(values, "DISCORD_BOT_TOKEN")
        profile_manifest_value = values.get("FORGE_PROFILES_FILE", "").strip()
        if profile_manifest_value:
            user_profiles = _load_profile_manifest(Path(profile_manifest_value))
        else:
            allowed_user_ids = _id_set(
                _required_text(values, "DISCORD_ALLOWED_USER_IDS"),
                "DISCORD_ALLOWED_USER_IDS",
            )
            profile = _legacy_profile(values)
            user_profiles = {user_id: profile for user_id in allowed_user_ids}
        guild_value = values.get("DISCORD_GUILD_ID", "").strip()
        guild_id = (
            _positive_integer(guild_value, "DISCORD_GUILD_ID") if guild_value else None
        )
        max_txt_bytes = _positive_integer(
            values.get("FORGE_MAX_TXT_BYTES", str(DEFAULT_MAX_TXT_BYTES)).strip(),
            "FORGE_MAX_TXT_BYTES",
        )
        model = values.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip() or DEFAULT_OPENAI_MODEL
        cover_letter_model = (
            values.get("OPENAI_COVER_LETTER_MODEL", model).strip() or model
        )
        return cls(
            token=token,
            user_profiles=user_profiles,
            guild_id=guild_id,
            model=model,
            cover_letter_model=cover_letter_model,
            context_model=values.get(
                "OPENAI_CONTEXT_MODEL", DEFAULT_CONTEXT_SELECTION_MODEL
            ).strip()
            or DEFAULT_CONTEXT_SELECTION_MODEL,
            web_model=values.get("OPENAI_WEB_MODEL", DEFAULT_WEB_SEARCH_MODEL).strip()
            or DEFAULT_WEB_SEARCH_MODEL,
            max_txt_bytes=max_txt_bytes,
        )

    @property
    def allowed_user_ids(self) -> FrozenSet[int]:
        return frozenset(self.user_profiles)

    def profile_for_user(self, user_id: int) -> Optional[CandidateProfile]:
        return self.user_profiles.get(user_id)

    def prepare(self) -> None:
        if not self.user_profiles:
            raise DiscordBotError("Forge has no authorized Discord profile mappings")
        profiles = {}
        for profile in self.user_profiles.values():
            existing = profiles.get(profile.profile_id)
            if existing is not None and existing != profile:
                raise DiscordBotError(
                    f"Forge profile ID {profile.profile_id!r} has conflicting configurations"
                )
            profiles[profile.profile_id] = profile

        for field_name in (
            "data",
            "cover_letter_data",
            "context",
            "database",
            "output_dir",
        ):
            owners = {}
            for profile in profiles.values():
                path = getattr(profile, field_name).resolve()
                other = owners.get(path)
                if other is not None:
                    raise DiscordBotError(
                        f"Forge profiles {other!r} and {profile.profile_id!r} share "
                        f"the same {field_name.replace('_', ' ')}: {path}"
                    )
                owners[path] = profile.profile_id

        for profile in profiles.values():
            profile.prepare()


@dataclass(frozen=True)
class TailorSource:
    kind: str
    url: Optional[str] = None
    text: Optional[str] = None


def _normalize_pasted_jd(value: str) -> str:
    """Remove non-semantic clipboard artifacts before enforcing the paste limit."""

    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace("\u00a0", " ").replace("\u202f", " ")
    normalized = normalized.translate(_PASTED_TEXT_IGNORABLES)
    return normalized.strip()


def validate_tailor_source(
    *,
    attachment_name: Optional[str],
    attachment_size: Optional[int],
    url: Optional[str],
    max_txt_bytes: int,
    jd: Optional[str] = None,
) -> TailorSource:
    normalized_input = url.strip() if isinstance(url, str) else ""
    normalized_jd = _normalize_pasted_jd(jd) if isinstance(jd, str) else ""
    has_attachment = attachment_name is not None
    has_url = bool(normalized_input)
    has_jd = bool(normalized_jd)
    if sum((has_attachment, has_url, has_jd)) != 1:
        raise DiscordBotError("Provide exactly one input: file, url, or jd")

    if has_attachment:
        filename = attachment_name or ""
        if Path(filename).suffix.lower() != ".txt":
            raise DiscordBotError("The file input must be a UTF-8 .txt file")
        if attachment_size is None or attachment_size < 0:
            raise DiscordBotError("Discord did not provide a valid attachment size")
        if attachment_size > max_txt_bytes:
            raise DiscordBotError(
                f"The .txt file is too large; maximum size is {max_txt_bytes} bytes"
            )
        return TailorSource(kind="file")

    if has_jd:
        character_count = len(normalized_jd)
        if character_count > MAX_PASTED_JD_LENGTH:
            raise DiscordBotError(
                f"Forge received {character_count:,} characters in jd after "
                f"normalization (limit: {MAX_PASTED_JD_LENGTH:,}). "
                "Use a UTF-8 .txt file for a longer description"
            )
        return TailorSource(kind="jd", text=normalized_jd)

    normalized_url, _ = normalize_job_url(normalized_input)
    return TailorSource(kind="url", url=normalized_url)


class ForgeDiscordRunner:
    """Serialize Discord requests and invoke the synchronous Forge workflow off-loop."""

    def __init__(
        self,
        config: DiscordBotConfig,
        tailor: Callable[..., TailoringResult] = tailor_resume_with_openai,
    ) -> None:
        self.config = config
        self._tailor = tailor
        self._busy = False

    @property
    def busy(self) -> bool:
        return self._busy

    async def run(
        self,
        *,
        user_id: int,
        attachment: Optional[discord.Attachment] = None,
        url: Optional[str] = None,
        jd: Optional[str] = None,
        cover_letter: bool = True,
    ) -> TailoringResult:
        profile = self.config.profile_for_user(user_id)
        if profile is None:
            raise DiscordBotError("You are not authorized to use this Forge bot")
        source = validate_tailor_source(
            attachment_name=attachment.filename if attachment is not None else None,
            attachment_size=attachment.size if attachment is not None else None,
            url=url,
            max_txt_bytes=self.config.max_txt_bytes,
            jd=jd,
        )
        if self._busy:
            raise DiscordBotBusyError(
                "Forge is already tailoring another application; try again when it finishes"
            )

        self._busy = True
        try:
            with tempfile.TemporaryDirectory(prefix="forge-discord-") as temp_dir:
                job_description = None
                job_description_url = source.url
                if attachment is not None:
                    try:
                        payload = await attachment.read()
                    except Exception as exc:
                        raise DiscordBotError(
                            f"Could not download the Discord attachment: {exc}"
                        ) from exc
                    if len(payload) > self.config.max_txt_bytes:
                        raise DiscordBotError(
                            "The downloaded .txt file exceeds the configured size limit"
                        )
                    try:
                        text = payload.decode("utf-8-sig")
                    except UnicodeDecodeError as exc:
                        raise DiscordBotError("The attached .txt file must use UTF-8") from exc
                    if not text.strip():
                        raise DiscordBotError("The attached .txt job description is empty")
                    job_description = Path(temp_dir) / "job-description.txt"
                    job_description.write_text(text, encoding="utf-8")
                elif source.kind == "jd":
                    job_description = Path(temp_dir) / "job-description.txt"
                    job_description.write_text(source.text or "", encoding="utf-8")

                return await asyncio.to_thread(
                    self._tailor,
                    template=profile.template,
                    data=profile.data,
                    schema=profile.schema,
                    bindings=profile.bindings,
                    job_description=job_description,
                    job_description_url=job_description_url,
                    candidate_context=profile.context,
                    context_database=profile.database,
                    usage_database=profile.database,
                    output_dir=profile.output_dir,
                    candidate_prefix=profile.filename_prefix,
                    model=self.config.model,
                    context_selection_model=self.config.context_model,
                    web_search_model=self.config.web_model,
                    include_pdf=True,
                    include_cover_letter=cover_letter,
                    cover_letter_template=profile.cover_letter_template,
                    cover_letter_data=profile.cover_letter_data,
                    cover_letter_schema=profile.cover_letter_schema,
                    cover_letter_bindings=profile.cover_letter_bindings,
                    cover_letter_prefix=profile.cover_letter_prefix,
                    cover_letter_model=self.config.cover_letter_model,
                )
        finally:
            self._busy = False


def _display_error(exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = exc.__class__.__name__
    return message[:1500]


def _success_message(result: TailoringResult, profile: CandidateProfile) -> str:
    summary = result.usage_summary
    cost = float(summary.get("estimated_cost_usd", 0.0))
    request_count = int(summary.get("requests", 0))
    company = f" at {result.company}" if result.company else ""
    gap_note = f"\nMaterial gaps reported: {len(result.gaps)}" if result.gaps else ""
    coverage = getattr(result, "keyword_coverage", None)
    coverage_note = ""
    if isinstance(coverage, Mapping):
        surfaced = int(coverage.get("surfacedAfter", 0))
        targeted = int(coverage.get("targetedKeywords", 0))
        percentage = float(coverage.get("percentage", 0.0))
        sections = coverage.get("changedSections", [])
        section_note = (
            f"\nSections tailored: {', '.join(str(item) for item in sections)}"
            if isinstance(sections, list) and sections
            else ""
        )
        coverage_note = (
            f"\nEvidence-backed keyword coverage: {surfaced}/{targeted} "
            f"({percentage:.1f}%){section_note}"
        )
    return (
        f"Profile: {profile.display_name}\n"
        f"Resume tailored for {result.job_title}{company}.\n"
        f"Cover letter: "
        f"{'included' if getattr(result, 'cover_letter_docx_output', None) else 'not requested'}\n"
        f"OpenAI requests: {request_count}\n"
        f"Estimated OpenAI cost: USD {cost:.8f}{coverage_note}{gap_note}"
    )


class ForgeDiscordClient(discord.Client):
    def __init__(
        self,
        config: DiscordBotConfig,
        tailor: Callable[..., TailoringResult] = tailor_resume_with_openai,
    ) -> None:
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(intents=intents)
        self.config = config
        self.runner = ForgeDiscordRunner(config, tailor=tailor)
        self.tree = app_commands.CommandTree(self)
        self.command_guild = (
            discord.Object(id=config.guild_id) if config.guild_id is not None else None
        )
        self.forge_group = app_commands.Group(
            name="forge",
            description="Tailor and render Axelyn Forge application documents",
        )

        @self.forge_group.command(
            name="tailor",
            description="Tailor a resume and cover letter from text, a file, or a job URL",
        )
        @app_commands.describe(
            file="UTF-8 .txt job description",
            url="Public job-posting URL",
            jd="Paste job-description text (Forge limit: 6,000 characters)",
            cover_letter="Also generate a tailored cover letter (default: Yes)",
        )
        async def tailor_command(
            interaction: discord.Interaction,
            file: Optional[discord.Attachment] = None,
            url: Optional[str] = None,
            jd: Optional[str] = None,
            cover_letter: bool = True,
        ) -> None:
            await self._handle_tailor(
                interaction,
                attachment=file,
                url=url,
                jd=jd,
                cover_letter=cover_letter,
            )

        @self.forge_group.command(
            name="whoami",
            description="Show your Discord user ID for Forge onboarding",
        )
        async def whoami_command(interaction: discord.Interaction) -> None:
            await self._handle_whoami(interaction)

        self.tree.add_command(self.forge_group, guild=self.command_guild)

    async def setup_hook(self) -> None:
        synced = await self.tree.sync(guild=self.command_guild)
        scope = f"guild {self.command_guild.id}" if self.command_guild else "global"
        LOGGER.info("Synced %d Discord application commands to %s", len(synced), scope)

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Forge Discord bot connected as %s (%s)", self.user, self.user.id)

    async def _handle_whoami(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            f"Your Discord user ID is `{interaction.user.id}`.\n"
            "Send this ID to the Forge administrator to be added to a candidate profile.",
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def _handle_tailor(
        self,
        interaction: discord.Interaction,
        *,
        attachment: Optional[discord.Attachment],
        url: Optional[str],
        jd: Optional[str] = None,
        cover_letter: bool = True,
    ) -> None:
        profile = self.config.profile_for_user(interaction.user.id)
        if profile is None:
            await interaction.response.send_message(
                "You are not authorized to use this Forge bot.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        try:
            validate_tailor_source(
                attachment_name=attachment.filename if attachment is not None else None,
                attachment_size=attachment.size if attachment is not None else None,
                url=url,
                max_txt_bytes=self.config.max_txt_bytes,
                jd=jd,
            )
        except ForgeError as exc:
            await interaction.response.send_message(
                f"Invalid request: {_display_error(exc)}\n"
                "Use `/forge tailor jd:<text>`, `/forge tailor file:<job.txt>`, "
                "or `/forge tailor url:<https://...>`.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        if self.runner.busy:
            await interaction.response.send_message(
                "Forge is already tailoring another application. Try again when it finishes.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.runner.run(
                user_id=interaction.user.id,
                attachment=attachment,
                url=url,
                jd=jd,
                cover_letter=cover_letter,
            )
            if result.pdf_output is None:
                raise DiscordBotError("Forge did not produce the expected PDF output")
            uploads = [
                discord.File(str(result.docx_output), filename=result.docx_output.name),
                discord.File(str(result.pdf_output), filename=result.pdf_output.name),
            ]
            if cover_letter:
                if (
                    result.cover_letter_docx_output is None
                    or result.cover_letter_pdf_output is None
                ):
                    raise DiscordBotError(
                        "Forge did not produce the expected cover-letter outputs"
                    )
                uploads.extend(
                    [
                        discord.File(
                            str(result.cover_letter_docx_output),
                            filename=result.cover_letter_docx_output.name,
                        ),
                        discord.File(
                            str(result.cover_letter_pdf_output),
                            filename=result.cover_letter_pdf_output.name,
                        ),
                    ]
                )
            try:
                await interaction.edit_original_response(
                    content=_success_message(result, profile),
                    attachments=uploads,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            finally:
                for upload in uploads:
                    upload.close()
        except ForgeError as exc:
            await interaction.edit_original_response(
                content=f"Forge could not tailor the application: {_display_error(exc)}",
                attachments=[],
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except Exception:
            LOGGER.exception("Unexpected Discord tailoring failure")
            await interaction.edit_original_response(
                content="Forge encountered an unexpected error. Check the VPS logs and try again.",
                attachments=[],
                allowed_mentions=discord.AllowedMentions.none(),
            )


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = DiscordBotConfig.from_environ()
        config.prepare()
    except ForgeError as exc:
        print(f"Forge Discord configuration error: {exc}", file=sys.stderr)
        return 2

    client = ForgeDiscordClient(config)
    client.run(config.token, log_handler=None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
