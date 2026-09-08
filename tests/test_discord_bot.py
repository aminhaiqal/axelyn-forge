import asyncio
import json
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord

from forge.discord_bot import (
    CandidateProfile,
    DiscordBotConfig,
    ForgeDiscordClient,
    ForgeDiscordRunner,
    validate_tailor_source,
)
from forge.errors import DiscordBotBusyError, DiscordBotError


def candidate_profile(**changes):
    values = {
        "profile_id": "amin",
        "display_name": "Muhammad Amin Haiqal",
    }
    values.update(changes)
    return CandidateProfile(**values)


def manifest_profile(profile_id):
    return {
        "displayName": profile_id.title(),
        "template": f"{profile_id}/resume.docx",
        "data": f"{profile_id}/resume.json",
        "schema": "shared/resume.schema.json",
        "bindings": f"{profile_id}/resume-bindings.json",
        "coverLetterTemplate": f"{profile_id}/cover-letter.docx",
        "coverLetterData": f"{profile_id}/cover-letter.json",
        "coverLetterSchema": "shared/cover-letter.schema.json",
        "coverLetterBindings": f"{profile_id}/cover-letter-bindings.json",
        "context": f"{profile_id}/context",
        "database": f"{profile_id}/context.sqlite3",
        "outputDir": f"{profile_id}/output",
        "filenamePrefix": f"{profile_id.title()}_Resume",
        "coverLetterPrefix": f"{profile_id.title()}_Cover_Letter",
    }


def bot_config(**changes):
    values = {
        "token": "discord-secret-token",
        "user_profiles": {42: candidate_profile()},
        "max_txt_bytes": 1024,
    }
    values.update(changes)
    return DiscordBotConfig(**values)


class FakeAttachment:
    def __init__(self, filename, payload, reported_size=None):
        self.filename = filename
        self.payload = payload
        self.size = len(payload) if reported_size is None else reported_size

    async def read(self):
        return self.payload


class FakeInteractionResponse:
    def __init__(self):
        self.messages = []
        self.deferred = None

    async def send_message(self, content, **kwargs):
        self.messages.append((content, kwargs))

    async def defer(self, **kwargs):
        self.deferred = kwargs


class FakeInteraction:
    def __init__(self, user_id=42):
        self.user = SimpleNamespace(id=user_id)
        self.response = FakeInteractionResponse()
        self.edits = []

    async def edit_original_response(self, **kwargs):
        attachments = kwargs.get("attachments", [])
        self.edits.append(
            {
                **kwargs,
                "attachment_names": [item.filename for item in attachments],
            }
        )


class DiscordBotConfigurationTests(unittest.TestCase):
    def test_environment_is_default_deny_and_token_is_hidden_from_repr(self):
        with self.assertRaisesRegex(DiscordBotError, "DISCORD_ALLOWED_USER_IDS"):
            DiscordBotConfig.from_environ({"DISCORD_BOT_TOKEN": "secret"})

        config = DiscordBotConfig.from_environ(
            {
                "DISCORD_BOT_TOKEN": "secret",
                "DISCORD_ALLOWED_USER_IDS": "42, 84",
                "DISCORD_GUILD_ID": "123",
            }
        )
        self.assertEqual(frozenset({42, 84}), config.allowed_user_ids)
        self.assertEqual(123, config.guild_id)
        self.assertNotIn("secret", repr(config))
        self.assertIs(config.profile_for_user(42), config.profile_for_user(84))

    def test_profile_manifest_maps_users_to_isolated_candidate_assets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            manifest = root / "profiles.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1",
                        "profiles": {
                            "amin": manifest_profile("amin"),
                            "sara": manifest_profile("sara"),
                        },
                        "discordUsers": {"42": "amin", "84": "sara"},
                    }
                ),
                encoding="utf-8",
            )

            config = DiscordBotConfig.from_environ(
                {
                    "DISCORD_BOT_TOKEN": "secret",
                    "FORGE_PROFILES_FILE": str(manifest),
                }
            )

            self.assertEqual(frozenset({42, 84}), config.allowed_user_ids)
            self.assertEqual("amin", config.profile_for_user(42).profile_id)
            self.assertEqual("sara", config.profile_for_user(84).profile_id)
            self.assertEqual(
                root / "sara" / "resume.json",
                config.profile_for_user(84).data,
            )
            self.assertEqual(
                root / "sara" / "context.sqlite3",
                config.profile_for_user(84).database,
            )

    def test_profile_manifest_rejects_unknown_profile_mapping(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            manifest = Path(temp_dir) / "profiles.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schemaVersion": "1",
                        "profiles": {"amin": manifest_profile("amin")},
                        "discordUsers": {"42": "missing"},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(DiscordBotError, "unknown Forge profile"):
                DiscordBotConfig.from_environ(
                    {
                        "DISCORD_BOT_TOKEN": "secret",
                        "FORGE_PROFILES_FILE": str(manifest),
                    }
                )

    def test_prepare_rejects_storage_shared_by_distinct_profiles(self):
        first = candidate_profile(
            profile_id="first",
            display_name="First",
            data=Path("first/resume.json"),
            cover_letter_data=Path("first/cover-letter.json"),
            context=Path("first/context"),
            output_dir=Path("first/output"),
        )
        second = candidate_profile(
            profile_id="second",
            display_name="Second",
            data=Path("second/resume.json"),
            cover_letter_data=Path("second/cover-letter.json"),
            context=Path("second/context"),
            output_dir=Path("second/output"),
        )
        config = bot_config(user_profiles={42: first, 84: second})

        with self.assertRaisesRegex(DiscordBotError, "share the same database"):
            config.prepare()

    def test_invalid_integer_configuration_is_rejected(self):
        with self.assertRaisesRegex(DiscordBotError, "positive integer"):
            DiscordBotConfig.from_environ(
                {
                    "DISCORD_BOT_TOKEN": "secret",
                    "DISCORD_ALLOWED_USER_IDS": "not-an-id",
                }
            )

    def test_tailor_command_has_sources_and_default_on_cover_letter_option(self):
        client = ForgeDiscordClient(bot_config())
        self.assertTrue(client.intents.guilds)
        self.assertFalse(client.intents.members)
        self.assertFalse(client.intents.message_content)
        self.assertFalse(client.intents.presences)
        group = client.tree.get_command("forge")
        self.assertIsNotNone(group)
        command = group.get_command("tailor")
        self.assertIsNotNone(command)
        parameters = {parameter.name: parameter for parameter in command.parameters}
        self.assertEqual({"file", "url", "jd", "cover_letter"}, set(parameters))
        self.assertEqual(discord.AppCommandOptionType.attachment, parameters["file"].type)
        self.assertEqual(discord.AppCommandOptionType.string, parameters["url"].type)
        self.assertEqual(discord.AppCommandOptionType.string, parameters["jd"].type)
        self.assertEqual(
            discord.AppCommandOptionType.boolean,
            parameters["cover_letter"].type,
        )
        self.assertFalse(parameters["file"].required)
        self.assertFalse(parameters["url"].required)
        self.assertFalse(parameters["jd"].required)
        self.assertFalse(parameters["cover_letter"].required)
        command_payload = command.to_dict(client.tree)
        option_payloads = {
            option["name"]: option for option in command_payload["options"]
        }
        self.assertNotIn("max_length", option_payloads["jd"])
        self.assertNotIn("min_length", option_payloads["jd"])
        self.assertIn("Forge limit: 6,000", option_payloads["jd"]["description"])
        self.assertIn("default: Yes", option_payloads["cover_letter"]["description"])


class DiscordTailorSourceTests(unittest.TestCase):
    def test_exactly_one_jd_file_or_url_is_required(self):
        for attachment_name, size, url, jd in (
            (None, None, None, None),
            ("jd.txt", 20, "https://example.com/jobs/1", None),
            ("jd.txt", 20, None, "Role requirements"),
            (None, None, "https://example.com/jobs/1", "Role requirements"),
        ):
            with self.subTest(attachment_name=attachment_name, url=url, jd=jd):
                with self.assertRaisesRegex(DiscordBotError, "exactly one"):
                    validate_tailor_source(
                        attachment_name=attachment_name,
                        attachment_size=size,
                        url=url,
                        max_txt_bytes=1024,
                        jd=jd,
                    )

    def test_jd_txt_file_and_public_url_are_accepted(self):
        jd_source = validate_tailor_source(
            attachment_name=None,
            attachment_size=None,
            url=None,
            max_txt_bytes=1024,
            jd="  Role requirements  ",
        )
        file_source = validate_tailor_source(
            attachment_name="job.TXT",
            attachment_size=20,
            url=None,
            max_txt_bytes=1024,
        )
        url_source = validate_tailor_source(
            attachment_name=None,
            attachment_size=None,
            url=" HTTPS://Careers.Example.com/jobs/1#apply ",
            max_txt_bytes=1024,
        )
        self.assertEqual("jd", jd_source.kind)
        self.assertEqual("Role requirements", jd_source.text)
        self.assertEqual("file", file_source.kind)
        self.assertEqual("url", url_source.kind)
        self.assertEqual("https://careers.example.com/jobs/1", url_source.url)

    def test_pasted_jd_normalizes_invisible_web_clipboard_artifacts(self):
        pasted_jd = "\ufeff" + ("x" * 5674) + ("\u200b" * 400)
        self.assertGreater(len(pasted_jd), 6000)

        source = validate_tailor_source(
            attachment_name=None,
            attachment_size=None,
            url=None,
            max_txt_bytes=1024,
            jd=pasted_jd,
        )

        self.assertEqual("jd", source.kind)
        self.assertEqual("x" * 5674, source.text)

    def test_non_txt_or_oversized_file_is_rejected(self):
        with self.assertRaisesRegex(DiscordBotError, "UTF-8 .txt"):
            validate_tailor_source(
                attachment_name="job.pdf",
                attachment_size=20,
                url=None,
                max_txt_bytes=1024,
            )
        with self.assertRaisesRegex(DiscordBotError, "too large"):
            validate_tailor_source(
                attachment_name="job.txt",
                attachment_size=1025,
                url=None,
                max_txt_bytes=1024,
            )
        with self.assertRaisesRegex(
            DiscordBotError,
            r"received 6,001 characters.*limit: 6,000.*UTF-8 \.txt",
        ):
            validate_tailor_source(
                attachment_name=None,
                attachment_size=None,
                url=None,
                max_txt_bytes=1024,
                jd="x" * 6001,
            )


class DiscordRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_id_selects_the_matching_candidate_profile(self):
        observed = {}
        sentinel = object()
        second = candidate_profile(
            profile_id="sara",
            display_name="Sara",
            data=Path("profiles/sara/resume.json"),
            context=Path("profiles/sara/context"),
            database=Path("profiles/sara/context.sqlite3"),
            output_dir=Path("profiles/sara/output"),
            filename_prefix="Sara_Resume",
        )

        def tailor(**kwargs):
            observed.update(kwargs)
            return sentinel

        runner = ForgeDiscordRunner(
            bot_config(user_profiles={42: candidate_profile(), 84: second}),
            tailor=tailor,
        )
        result = await runner.run(user_id=84, jd="Role requirements")

        self.assertIs(sentinel, result)
        self.assertEqual(second.data, observed["data"])
        self.assertEqual(second.context, observed["candidate_context"])
        self.assertEqual(second.database, observed["context_database"])
        self.assertEqual(second.database, observed["usage_database"])
        self.assertEqual(second.output_dir, observed["output_dir"])
        self.assertEqual("Sara_Resume", observed["candidate_prefix"])

    async def test_direct_jd_becomes_existing_temporary_jd_for_forge(self):
        observed = {}
        sentinel = object()

        def tailor(**kwargs):
            observed.update(kwargs)
            observed["jd_text"] = kwargs["job_description"].read_text(
                encoding="utf-8"
            )
            self.assertTrue(kwargs["job_description"].is_file())
            return sentinel

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        result = await runner.run(user_id=42, jd="  Role\u200b requirements ✓  ")

        self.assertIs(sentinel, result)
        self.assertEqual("Role requirements ✓", observed["jd_text"])
        self.assertIsNone(observed["job_description_url"])
        self.assertTrue(observed["include_pdf"])
        self.assertTrue(observed["include_cover_letter"])
        self.assertEqual(
            Path("templates/Amin_Haiqal_Cover_Letter_SDT_Template.docx"),
            observed["cover_letter_template"],
        )
        self.assertFalse(observed["job_description"].exists())

    async def test_cover_letter_false_is_forwarded_without_changing_jd_handling(self):
        observed = {}
        sentinel = object()

        def tailor(**kwargs):
            observed.update(kwargs)
            return sentinel

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        result = await runner.run(
            user_id=42,
            jd="Role requirements",
            cover_letter=False,
        )

        self.assertIs(sentinel, result)
        self.assertFalse(observed["include_cover_letter"])

    async def test_txt_attachment_becomes_existing_temporary_jd_for_forge(self):
        observed = {}
        sentinel = object()

        def tailor(**kwargs):
            observed.update(kwargs)
            observed["jd_text"] = kwargs["job_description"].read_text(encoding="utf-8")
            self.assertTrue(kwargs["job_description"].is_file())
            return sentinel

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        result = await runner.run(
            user_id=42,
            attachment=FakeAttachment("job.txt", "Role requirements ✓".encode("utf-8"))
        )

        self.assertIs(sentinel, result)
        self.assertEqual("Role requirements ✓", observed["jd_text"])
        self.assertIsNone(observed["job_description_url"])
        self.assertFalse(observed["job_description"].exists())
        self.assertEqual(Path("data/context.sqlite3"), observed["usage_database"])

    async def test_url_is_normalized_and_forwarded_to_forge(self):
        observed = {}
        sentinel = object()

        def tailor(**kwargs):
            observed.update(kwargs)
            return sentinel

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        result = await runner.run(
            user_id=42,
            url="HTTPS://Careers.Example.com/jobs/1#apply",
        )

        self.assertIs(sentinel, result)
        self.assertIsNone(observed["job_description"])
        self.assertEqual(
            "https://careers.example.com/jobs/1",
            observed["job_description_url"],
        )

    async def test_invalid_utf8_is_rejected(self):
        runner = ForgeDiscordRunner(bot_config(), tailor=lambda **kwargs: None)
        with self.assertRaisesRegex(DiscordBotError, "UTF-8"):
            await runner.run(
                user_id=42,
                attachment=FakeAttachment("job.txt", b"\xff\xfe"),
            )

    async def test_concurrent_request_is_rejected_instead_of_queued(self):
        started = threading.Event()
        release = threading.Event()

        def tailor(**kwargs):
            started.set()
            release.wait(timeout=2)
            return object()

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        first = asyncio.create_task(
            runner.run(user_id=42, url="https://example.com/jobs/1")
        )
        await asyncio.to_thread(started.wait, 1)
        try:
            with self.assertRaises(DiscordBotBusyError):
                await runner.run(user_id=42, url="https://example.com/jobs/2")
        finally:
            release.set()
        await first


class DiscordInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_default_request_returns_resume_and_cover_letter_docx_and_pdf(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "Amin_Haiqal_Resume_Engineer.docx"
            output.write_bytes(b"test-docx")
            pdf_output = output.with_suffix(".pdf")
            pdf_output.write_bytes(b"test-pdf")
            cover_output = Path(temp_dir) / "Amin_Haiqal_Cover_Letter_Example_Engineer.docx"
            cover_output.write_bytes(b"test-cover-docx")
            cover_pdf_output = cover_output.with_suffix(".pdf")
            cover_pdf_output.write_bytes(b"test-cover-pdf")

            def tailor(**kwargs):
                return SimpleNamespace(
                    docx_output=output,
                    pdf_output=pdf_output,
                    cover_letter_docx_output=cover_output,
                    cover_letter_pdf_output=cover_pdf_output,
                    job_title="Engineer",
                    company="Example",
                    usage_summary={"requests": 2, "estimated_cost_usd": 0.0123},
                    keyword_coverage={
                        "surfacedAfter": 10,
                        "targetedKeywords": 12,
                        "percentage": 83.3,
                        "changedSections": ["Summary", "Experience", "Projects"],
                    },
                    gaps=(),
                )

            client = ForgeDiscordClient(bot_config(), tailor=tailor)
            interaction = FakeInteraction()
            await client._handle_tailor(
                interaction,
                attachment=None,
                url=None,
                jd="Job requirements",
            )

            self.assertEqual({"ephemeral": True, "thinking": True}, interaction.response.deferred)
            self.assertEqual([], interaction.response.messages)
            self.assertEqual(1, len(interaction.edits))
            self.assertEqual(
                [
                    output.name,
                    pdf_output.name,
                    cover_output.name,
                    cover_pdf_output.name,
                ],
                interaction.edits[0]["attachment_names"],
            )
            self.assertIn("Cover letter: included", interaction.edits[0]["content"])
            self.assertIn(
                "Profile: Muhammad Amin Haiqal",
                interaction.edits[0]["content"],
            )
            self.assertIn("Estimated OpenAI cost: USD 0.01230000", interaction.edits[0]["content"])
            self.assertIn(
                "Evidence-backed keyword coverage: 10/12 (83.3%)",
                interaction.edits[0]["content"],
            )
            self.assertIn(
                "Sections tailored: Summary, Experience, Projects",
                interaction.edits[0]["content"],
            )

    async def test_cover_letter_false_returns_only_resume_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "Amin_Haiqal_Resume_Engineer.docx"
            output.write_bytes(b"test-docx")
            pdf_output = output.with_suffix(".pdf")
            pdf_output.write_bytes(b"test-pdf")
            observed = {}

            def tailor(**kwargs):
                observed.update(kwargs)
                return SimpleNamespace(
                    docx_output=output,
                    pdf_output=pdf_output,
                    cover_letter_docx_output=None,
                    cover_letter_pdf_output=None,
                    job_title="Engineer",
                    company="Example",
                    usage_summary={"requests": 1, "estimated_cost_usd": 0.01},
                    keyword_coverage=None,
                    gaps=(),
                )

            client = ForgeDiscordClient(bot_config(), tailor=tailor)
            interaction = FakeInteraction()
            await client._handle_tailor(
                interaction,
                attachment=None,
                url=None,
                jd="Job requirements",
                cover_letter=False,
            )

            self.assertFalse(observed["include_cover_letter"])
            self.assertEqual(
                [output.name, pdf_output.name],
                interaction.edits[0]["attachment_names"],
            )
            self.assertIn("Cover letter: not requested", interaction.edits[0]["content"])

    async def test_unauthorized_or_ambiguous_request_never_runs_forge(self):
        calls = []
        client = ForgeDiscordClient(
            bot_config(),
            tailor=lambda **kwargs: calls.append(kwargs),
        )

        unauthorized = FakeInteraction(user_id=99)
        await client._handle_tailor(
            unauthorized,
            attachment=FakeAttachment("job.txt", b"Job requirements"),
            url=None,
        )
        self.assertIn("not authorized", unauthorized.response.messages[0][0])
        self.assertTrue(unauthorized.response.messages[0][1]["ephemeral"])

        ambiguous = FakeInteraction()
        await client._handle_tailor(
            ambiguous,
            attachment=FakeAttachment("job.txt", b"Job requirements"),
            url="https://example.com/jobs/1",
        )
        self.assertIn("Provide exactly one", ambiguous.response.messages[0][0])
        self.assertTrue(ambiguous.response.messages[0][1]["ephemeral"])
        self.assertEqual([], calls)


if __name__ == "__main__":
    unittest.main()
