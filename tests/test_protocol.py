"""JSON actions, tick echo, and the queued-observation rule."""
from __future__ import annotations

import copy
import json
import os
import select
import subprocess
import sys
import time
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from combat.pilot import CombatBot
from tests.support import ROOT, fresh_obs, hello_without_map, load_stream, schema


class ActionShapeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stream = load_stream()
        cls.hello = hello_without_map(cls.stream)
        cls.schema = schema()
        cls.bot = CombatBot(cls.hello)

    def test_ready_document_and_action_documents_validate(self):
        ready = {"type": "ready", "name": "phantom-duelist"}
        self.assertEqual(self.schema.errors(ready, "Ready"), [])
        encoded = json.dumps(ready, allow_nan=False)
        self.assertLess(len(encoded.encode()), 65536)

        obs = fresh_obs(self.stream)
        obs["tick"] = 508
        action = self.bot.act(obs)
        self.assertEqual(action["tick"], 508)
        self.assertEqual(self.schema.errors(action, "Action"), [])
        raw = json.dumps(action, allow_nan=False, separators=(",", ":"))
        self.assertLess(len(raw.encode()), 65536)
        self.assertEqual(len(action["fire"]), 2)
        self.assertTrue(all(isinstance(flag, bool) for flag in action["fire"]))
        self.assertLessEqual((action["move"][0] ** 2 + action["move"][1] ** 2) ** 0.5, 1.0 + 1e-9)

    def test_every_recorded_observation_echoes_its_tick(self):
        bot = CombatBot(self.hello)
        checked = 0
        for msg in self.stream:
            if msg.get("type") != "obs":
                continue
            action = bot.act(msg)
            self.assertEqual(action["tick"], msg["tick"])
            errors = self.schema.errors(action, "Action")
            self.assertEqual(errors, [], errors)
            json.dumps(action, allow_nan=False)
            checked += 1
        self.assertEqual(checked, 300)


class SubprocessProtocolTest(unittest.TestCase):
    def test_ready_tick_echo_and_newest_observation(self):
        stream = load_stream()
        hello = copy.deepcopy(stream[0])
        hello["map"]["dir"] = os.path.join(ROOT, "arena")
        observations = [msg for msg in stream if msg.get("type") == "obs"]
        end = stream[-1]
        proc = subprocess.Popen(
            [sys.executable, "-u", os.path.join(ROOT, "bot.py")],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            self._send(proc, hello)
            ready = self._read_json(proc, 5.0)
            self.assertEqual(ready.get("type"), "ready")
            self.assertEqual(ready.get("name"), "phantom-duelist")

            self._send(proc, observations[0])
            first = self._read_json(proc, 2.0)
            self.assertEqual(first.get("tick"), observations[0]["tick"])

            newer = observations[10]
            older = observations[8]
            # One write, the way a bot that fell behind sees a queue.
            blob = (
                json.dumps(older, separators=(",", ":")) + "\n"
                + json.dumps(newer, separators=(",", ":")) + "\n"
            ).encode()
            proc.stdin.write(blob)
            proc.stdin.flush()
            lines = self._read_until(proc, 2.0)
            ticks = [line.get("tick") for line in lines]
            self.assertIn(newer["tick"], ticks)
            self.assertEqual(ticks[-1], newer["tick"])

            self._send(proc, end)
            proc.stdin.close()
            code = proc.wait(timeout=3)
            self.assertEqual(code, 0)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=2)
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                if stream is not None:
                    stream.close()

    def _send(self, proc, msg):
        proc.stdin.write((json.dumps(msg, separators=(",", ":")) + "\n").encode())
        proc.stdin.flush()

    def _read_json(self, proc, timeout):
        line = self._readline(proc, timeout)
        self.assertTrue(line, "bot produced no line")
        return json.loads(line)

    def _readline(self, proc, timeout):
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.1)
            if ready:
                return proc.stdout.readline()
            if proc.poll() is not None:
                err = proc.stderr.read().decode("utf-8", "replace")
                self.fail(f"bot exited early: {err[-500:]}")
        err = b""
        if proc.stderr:
            # Non-blocking peek is not worth it; the timeout message is enough.
            pass
        self.fail("timed out waiting for the bot")

    def _read_until(self, proc, timeout):
        deadline = time.perf_counter() + timeout
        lines = []
        while time.perf_counter() < deadline:
            ready, _, _ = select.select([proc.stdout], [], [], 0.05)
            if not ready:
                if lines:
                    return lines
                continue
            raw = proc.stdout.readline()
            if not raw:
                break
            lines.append(json.loads(raw))
            # The newest answer is one line. Give a short beat for a stale
            # extra, then stop. Either way the last tick must be the newest.
            if len(lines) >= 1:
                extra, _, _ = select.select([proc.stdout], [], [], 0.15)
                if not extra:
                    return lines
        self.assertTrue(lines, "no action for the queued observations")
        return lines


if __name__ == "__main__":
    unittest.main()
