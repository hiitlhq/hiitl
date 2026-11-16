"""Row 135 (HTL-29 review, condition 4), in the SDK's audit store: a result is recorded once, and is answered from what
its write stored.

The spec: event_format.md "The Lifecycle", "One step": the read of an action's records and its result's write are one
step, and a result is answered from the record as its write stored it, read in the write's own transaction. Security
architecture §1.1, "A change record names what it replaced, and a change is answered from what it wrote". Design: the
HTL-29 test design, row 135, behavior 14. Mirrors typescript/packages/sdk/tests/unit/row135.test.ts.

The two-writer cell holds the first result after its read of the action's records, where the race lives, and lets it
go once the second waits on the action or finishes, read from the store's own holds, never from a timer.
"""

from __future__ import annotations

import sqlite3
import threading

import pytest

from hiitl import LifecycleError
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.tests.test_row150 import ORG, _client
from hiitl.sdk.tests.test_row160 import _most_on_one_key


def _results(h, action_id) -> list:
    return [r for r in h._audit_logger.lifecycle(ORG, "dev", action_id) if r.get("execution_result")]


def _race(clients, action_ids, monkeypatch):
    """Two results on two threads, the first held after its read of the action's records until the second waits on its
    action or finishes. Returns the two answers (or what each raised) and whether the second had finished when the first
    was let go."""
    read, go = threading.Event(), threading.Event()
    reader = AuditLogger.lifecycle

    def held(self, *args):
        found = reader(self, *args)
        if not read.is_set():
            read.set()
            go.wait()
        return found

    monkeypatch.setattr(AuditLogger, "lifecycle", held)
    answers = [None, None]

    def call(n, status):
        try:
            answers[n] = clients[n].record_result(action_ids[n], status, error=None if status == "succeeded" else "x")
        except LifecycleError as e:
            answers[n] = e

    threads = [threading.Thread(target=call, args=(0, "succeeded")), threading.Thread(target=call, args=(1, "failed"))]
    threads[0].start()
    read.wait()
    threads[1].start()
    while threads[1].is_alive() and _most_on_one_key() < 2:
        threads[1].join(0.001)
    second_finished = not threads[1].is_alive()
    go.set()
    for t in threads:
        t.join()
    monkeypatch.undo()
    return answers, second_finished


def test_two_results_for_one_action_in_one_store_record_one(tmp_path, monkeypatch):
    """Two clients of one store, one thread each, record different results for one action: one is recorded, and the
    other is refused as the store's second result."""
    clients = [_client(tmp_path), _client(tmp_path)]
    action_id = clients[0].evaluate("refund", parameters={"amount": 10}).action_id
    answers, second_finished = _race(clients, [action_id, action_id], monkeypatch)

    results = _results(clients[0], action_id)
    assert [r["event_id"] for r in results] == [answers[0]["event_id"]], "one result, the first's"
    assert isinstance(answers[1], LifecycleError) and answers[1].reason == "RESULT_ALREADY_RECORDED", answers[1]
    assert not second_finished, "the second result waited on the action"
    assert AuditLogger._holds == {}, "an action no call holds or waits on is dropped"


def test_a_result_for_another_action_does_not_wait(tmp_path, monkeypatch):
    h = _client(tmp_path)
    actions = [h.evaluate("refund", parameters={"amount": n}).action_id for n in (10, 20)]
    answers, second_finished = _race([h, h], actions, monkeypatch)

    assert second_finished, "the second result, for another action, finished while the first was held"
    assert [len(_results(h, a)) for a in actions] == [1, 1], answers


def _reads_fail_after_a_write_commits(monkeypatch) -> dict:
    """Once armed, every statement the store runs after a write commits fails, as a store whose disk fails after it
    acknowledges the commit: what the write stored is in the file, and nothing more can be read from it."""
    state = {"armed": False, "committed": False}
    connect = sqlite3.connect

    class Cursor(sqlite3.Cursor):
        def execute(self, sql, *args):
            if state["committed"]:
                raise sqlite3.OperationalError("disk I/O error")
            if state["armed"] and sql.lstrip().upper().startswith("INSERT"):
                self.connection.wrote = True
            return super().execute(sql, *args)

    class Connection(sqlite3.Connection):
        wrote = False

        def cursor(self, factory=Cursor):
            return super().cursor(factory)

        def execute(self, sql, *args):
            return self.cursor().execute(sql, *args)

        def commit(self):
            super().commit()
            state["committed"] = state["committed"] or self.wrote

    monkeypatch.setattr(sqlite3, "connect", lambda *a, **kw: connect(*a, **{**kw, "factory": Connection}))
    return state


def test_a_result_is_answered_from_its_write_whatever_a_read_after_it_meets(tmp_path, monkeypatch):
    """The result's write commits, and every read after it fails: the result recorded is the result answered."""
    h = _client(tmp_path)
    action_id = h.evaluate("refund", parameters={"amount": 10}).action_id
    failing = _reads_fail_after_a_write_commits(monkeypatch)
    failing["armed"] = True
    try:
        answer = h.record_result(action_id, "succeeded", duration_ms=12)
    except Exception as e:                      # what its caller would be told in place of what it wrote
        pytest.fail(f"the result raised once its write had committed: {e!r}")
    finally:
        monkeypatch.undo()

    (stored,) = _results(h, action_id)
    assert (answer["event_id"], answer["content_hash"], answer["execution_result"]) == (
        stored["event_id"], stored["content_hash"], stored["execution_result"]), "the result answered is the one stored"


def test_a_repeated_result_is_answered_with_the_first(tmp_path):
    """The hold does not change a repeat: the same result again is answered with the record the first wrote."""
    h = _client(tmp_path)
    action_id = h.evaluate("refund", parameters={"amount": 10}).action_id
    first, again = (h.record_result(action_id, "succeeded", duration_ms=12) for _ in range(2))
    assert again["event_id"] == first["event_id"] and len(_results(h, action_id)) == 1
