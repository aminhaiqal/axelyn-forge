import asyncio
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace

import discord

from forge.discord_bot import (
    DiscordBotConfig,
    ForgeDiscordClient,
    ForgeDiscordRunner,
    validate_tailor_source,
)
from forge.errors import DiscordBotBusyError, DiscordBotError


def bot_config(**changes):
    values = {
        "token": "discord-secret-token",
        "allowed_user_ids": frozenset({42}),
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

    def test_invalid_integer_configuration_is_rejected(self):
        with self.assertRaisesRegex(DiscordBotError, "positive integer"):
            DiscordBotConfig.from_environ(
                {
                    "DISCORD_BOT_TOKEN": "secret",
                    "DISCORD_ALLOWED_USER_IDS": "not-an-id",
                }
            )

    def test_single_grouped_tailor_command_has_jd_file_and_url_options(self):
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
        self.assertEqual({"file", "url", "jd"}, set(parameters))
        self.assertEqual(discord.AppCommandOptionType.attachment, parameters["file"].type)
        self.assertEqual(discord.AppCommandOptionType.string, parameters["url"].type)
        self.assertEqual(discord.AppCommandOptionType.string, parameters["jd"].type)
        self.assertFalse(parameters["file"].required)
        self.assertFalse(parameters["url"].required)
        self.assertFalse(parameters["jd"].required)
        command_payload = command.to_dict(client.tree)
        option_payloads = {
            option["name"]: option for option in command_payload["options"]
        }
        self.assertEqual(6000, option_payloads["jd"]["max_length"])


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
        with self.assertRaisesRegex(DiscordBotError, "use a .txt file"):
            validate_tailor_source(
                attachment_name=None,
                attachment_size=None,
                url=None,
                max_txt_bytes=1024,
                jd="x" * 6001,
            )


class DiscordRunnerTests(unittest.IsolatedAsyncioTestCase):
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
        result = await runner.run(jd="  Role requirements ✓  ")

        self.assertIs(sentinel, result)
        self.assertEqual("Role requirements ✓", observed["jd_text"])
        self.assertIsNone(observed["job_description_url"])
        self.assertFalse(observed["job_description"].exists())

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
        result = await runner.run(url="HTTPS://Careers.Example.com/jobs/1#apply")

        self.assertIs(sentinel, result)
        self.assertIsNone(observed["job_description"])
        self.assertEqual(
            "https://careers.example.com/jobs/1",
            observed["job_description_url"],
        )

    async def test_invalid_utf8_is_rejected(self):
        runner = ForgeDiscordRunner(bot_config(), tailor=lambda **kwargs: None)
        with self.assertRaisesRegex(DiscordBotError, "UTF-8"):
            await runner.run(attachment=FakeAttachment("job.txt", b"\xff\xfe"))

    async def test_concurrent_request_is_rejected_instead_of_queued(self):
        started = threading.Event()
        release = threading.Event()

        def tailor(**kwargs):
            started.set()
            release.wait(timeout=2)
            return object()

        runner = ForgeDiscordRunner(bot_config(), tailor=tailor)
        first = asyncio.create_task(runner.run(url="https://example.com/jobs/1"))
        await asyncio.to_thread(started.wait, 1)
        try:
            with self.assertRaises(DiscordBotBusyError):
                await runner.run(url="https://example.com/jobs/2")
        finally:
            release.set()
        await first


class DiscordInteractionTests(unittest.IsolatedAsyncioTestCase):
    async def test_authorized_request_is_deferred_privately_and_returns_docx(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "Amin_Haiqal_Resume_Engineer.docx"
            output.write_bytes(b"test-docx")

            def tailor(**kwargs):
                return SimpleNamespace(
                    docx_output=output,
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
            self.assertEqual([output.name], interaction.edits[0]["attachment_names"])
            self.assertIn("Estimated OpenAI cost: USD 0.01230000", interaction.edits[0]["content"])
            self.assertIn(
                "Evidence-backed keyword coverage: 10/12 (83.3%)",
                interaction.edits[0]["content"],
            )
            self.assertIn(
                "Sections tailored: Summary, Experience, Projects",
                interaction.edits[0]["content"],
            )

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
