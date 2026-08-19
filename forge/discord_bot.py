"""Private Discord application-command adapter for Axelyn Forge."""

import asyncio
import logging
import os
import sys
import tempfile
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
DISCORD_MAX_STRING_OPTION_LENGTH = 6000


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
class DiscordBotConfig:
    token: str = field(repr=False)
    allowed_user_ids: FrozenSet[int]
    guild_id: Optional[int] = None
    template: Path = Path("templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx")
    data: Path = Path("data/profile.json")
    schema: Path = Path("schemas/profile.schema.json")
    bindings: Path = Path("bindings/software-engineer.json")
    context: Path = Path("context")
    database: Path = Path("data/context.sqlite3")
    output_dir: Path = Path("output")
    filename_prefix: str = "Amin_Haiqal_Resume"
    model: str = DEFAULT_OPENAI_MODEL
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
        allowed_user_ids = _id_set(
            _required_text(values, "DISCORD_ALLOWED_USER_IDS"),
            "DISCORD_ALLOWED_USER_IDS",
        )
        guild_value = values.get("DISCORD_GUILD_ID", "").strip()
        guild_id = (
            _positive_integer(guild_value, "DISCORD_GUILD_ID") if guild_value else None
        )
        max_txt_bytes = _positive_integer(
            values.get("FORGE_MAX_TXT_BYTES", str(DEFAULT_MAX_TXT_BYTES)).strip(),
            "FORGE_MAX_TXT_BYTES",
        )
        return cls(
            token=token,
            allowed_user_ids=allowed_user_ids,
            guild_id=guild_id,
            template=Path(
                values.get(
                    "FORGE_TEMPLATE",
                    "templates/Amin_Haiqal_Resume_Forge_SDT_Template.docx",
                )
            ),
            data=Path(values.get("FORGE_DATA", "data/profile.json")),
            schema=Path(values.get("FORGE_SCHEMA", "schemas/profile.schema.json")),
            bindings=Path(
                values.get("FORGE_BINDINGS", "bindings/software-engineer.json")
            ),
            context=Path(values.get("FORGE_CONTEXT", "context")),
            database=Path(values.get("FORGE_DATABASE", "data/context.sqlite3")),
            output_dir=Path(values.get("FORGE_OUTPUT_DIR", "output")),
            filename_prefix=values.get(
                "FORGE_FILENAME_PREFIX", "Amin_Haiqal_Resume"
            ).strip()
            or "Amin_Haiqal_Resume",
            model=values.get("OPENAI_MODEL", DEFAULT_OPENAI_MODEL).strip()
            or DEFAULT_OPENAI_MODEL,
            context_model=values.get(
                "OPENAI_CONTEXT_MODEL", DEFAULT_CONTEXT_SELECTION_MODEL
            ).strip()
            or DEFAULT_CONTEXT_SELECTION_MODEL,
            web_model=values.get("OPENAI_WEB_MODEL", DEFAULT_WEB_SEARCH_MODEL).strip()
            or DEFAULT_WEB_SEARCH_MODEL,
            max_txt_bytes=max_txt_bytes,
        )

    def prepare(self) -> None:
        assets = {
            "template": self.template,
            "resume data": self.data,
            "schema": self.schema,
            "bindings": self.bindings,
        }
        missing = [f"{label}: {path}" for label, path in assets.items() if not path.is_file()]
        if not self.context.exists():
            missing.append(f"context: {self.context}")
        if missing:
            raise DiscordBotError("Missing Forge runtime assets:\n- " + "\n- ".join(missing))
        try:
            self.database.parent.mkdir(parents=True, exist_ok=True)
            self.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise DiscordBotError(f"Could not prepare persistent Forge directories: {exc}") from exc


@dataclass(frozen=True)
class TailorSource:
    kind: str
    url: Optional[str] = None
    text: Optional[str] = None


def validate_tailor_source(
    *,
    attachment_name: Optional[str],
    attachment_size: Optional[int],
    url: Optional[str],
    max_txt_bytes: int,
    jd: Optional[str] = None,
) -> TailorSource:
    normalized_input = url.strip() if isinstance(url, str) else ""
    normalized_jd = jd.strip() if isinstance(jd, str) else ""
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
        if len(normalized_jd) > DISCORD_MAX_STRING_OPTION_LENGTH:
            raise DiscordBotError(
                "The jd input is too long; use a .txt file for descriptions over "
                f"{DISCORD_MAX_STRING_OPTION_LENGTH:,} characters"
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
        attachment: Optional[discord.Attachment] = None,
        url: Optional[str] = None,
        jd: Optional[str] = None,
    ) -> TailoringResult:
        source = validate_tailor_source(
            attachment_name=attachment.filename if attachment is not None else None,
            attachment_size=attachment.size if attachment is not None else None,
            url=url,
            max_txt_bytes=self.config.max_txt_bytes,
            jd=jd,
        )
        if self._busy:
            raise DiscordBotBusyError(
                "Forge is already tailoring another resume; try again when it finishes"
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
                    template=self.config.template,
                    data=self.config.data,
                    schema=self.config.schema,
                    bindings=self.config.bindings,
                    job_description=job_description,
                    job_description_url=job_description_url,
                    candidate_context=self.config.context,
                    context_database=self.config.database,
                    usage_database=self.config.database,
                    output_dir=self.config.output_dir,
                    candidate_prefix=self.config.filename_prefix,
                    model=self.config.model,
                    context_selection_model=self.config.context_model,
                    web_search_model=self.config.web_model,
                    include_pdf=True,
                )
        finally:
            self._busy = False


def _display_error(exc: BaseException) -> str:
    message = " ".join(str(exc).split())
    if not message:
        message = exc.__class__.__name__
    return message[:1500]


def _success_message(result: TailoringResult) -> str:
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
        f"Resume tailored for {result.job_title}{company}.\n"
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
            description="Tailor and render an Axelyn Forge resume",
        )

        @self.forge_group.command(
            name="tailor",
            description="Tailor a resume from pasted text, a .txt file, or a job-posting URL",
        )
        @app_commands.describe(
            file="UTF-8 .txt job description",
            url="Public job-posting URL",
            jd="Job-description text, up to 6,000 characters",
        )
        async def tailor_command(
            interaction: discord.Interaction,
            file: Optional[discord.Attachment] = None,
            url: Optional[str] = None,
            jd: Optional[
                app_commands.Range[str, 1, DISCORD_MAX_STRING_OPTION_LENGTH]
            ] = None,
        ) -> None:
            await self._handle_tailor(interaction, attachment=file, url=url, jd=jd)

        self.tree.add_command(self.forge_group, guild=self.command_guild)

    async def setup_hook(self) -> None:
        synced = await self.tree.sync(guild=self.command_guild)
        scope = f"guild {self.command_guild.id}" if self.command_guild else "global"
        LOGGER.info("Synced %d Discord application commands to %s", len(synced), scope)

    async def on_ready(self) -> None:
        if self.user is not None:
            LOGGER.info("Forge Discord bot connected as %s (%s)", self.user, self.user.id)

    async def _handle_tailor(
        self,
        interaction: discord.Interaction,
        *,
        attachment: Optional[discord.Attachment],
        url: Optional[str],
        jd: Optional[str] = None,
    ) -> None:
        if interaction.user.id not in self.config.allowed_user_ids:
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
                "Forge is already tailoring another resume. Try again when it finishes.",
                ephemeral=True,
                allowed_mentions=discord.AllowedMentions.none(),
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            result = await self.runner.run(attachment=attachment, url=url, jd=jd)
            if result.pdf_output is None:
                raise DiscordBotError("Forge did not produce the expected PDF output")
            uploads = [
                discord.File(str(result.docx_output), filename=result.docx_output.name),
                discord.File(str(result.pdf_output), filename=result.pdf_output.name),
            ]
            try:
                await interaction.edit_original_response(
                    content=_success_message(result),
                    attachments=uploads,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            finally:
                for upload in uploads:
                    upload.close()
        except ForgeError as exc:
            await interaction.edit_original_response(
                content=f"Forge could not tailor the resume: {_display_error(exc)}",
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
