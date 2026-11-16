"""Row 160 (HTL-29): in an SDK's audit store, the dedup read and the record's write are one step.

The ruling (HTL-29, 2026-11-09): "dedup read and write are one step under the same lock on (org, environment, key); the
index stays non-unique (24 h window)". Principle 5: "Embrace idempotency, retries, deduplication, and partial failure as
first-class concerns." The spec is docs/specs/ecp_evaluate_spec.md §4, the paragraph "The read and the write are one
step". Design: the HTL-29 test design, row 160, behavior 7.

Each cell holds the first call after its dedup read, where the race lives, and lets it go once the second call waits on
the key or finishes, read from the store's own holds, never from a timer.
"""

from __future__ import annotations

import os
import threading

import pytest

from hiitl.core.evaluator import PolicyEvaluator
from hiitl.sdk.audit import AuditLogger
from hiitl.sdk.client import HIITL


def _client(tmp_path):
    return HIITL(audit_db_path=str(tmp_path / "a.db"))


def _another_name(tmp_path, form):
    """A second name of the store at tmp_path/a.db, made once the store exists, as a mount or a link makes one."""
    store = tmp_path / "a.db"
    if form == "directory-link":
        (tmp_path / "alias").symlink_to(tmp_path, target_is_directory=True)
        return tmp_path / "alias" / "a.db"
    if form == "file-link":
        (tmp_path / "link.db").symlink_to(store)
        return tmp_path / "link.db"
    os.link(store, tmp_path / "hard.db")
    return tmp_path / "hard.db"


def _records(tmp_path):
    return AuditLogger(str(tmp_path / "a.db")).get_unsynced(limit=10)


def _most_on_one_key() -> int:
    """The most calls holding or waiting on any one key of any store."""
    return max((callers for _, callers in AuditLogger._holds.values()), default=0)


def _held_after_the_first_read(monkeypatch):
    """The first dedup read, held until `go` is set; `read` is set once it has read."""
    read, go = threading.Event(), threading.Event()
    reader = AuditLogger.first_decision_under_key

    def held(self, *args):
        found = reader(self, *args)
        if not read.is_set():
            read.set()
            go.wait()
        return found

    monkeypatch.setattr(AuditLogger, "first_decision_under_key", held)
    return read, go


def _race(clients, keys, monkeypatch):
    """Two calls on two threads, the first held after its dedup read until the second waits on its key or finishes.
    Returns the two decisions and whether the second had finished when the first was let go."""
    read, go = _held_after_the_first_read(monkeypatch)
    answers = [None, None]

    def call(n):
        answers[n] = clients[n].evaluate("refund", parameters={"amount": 10}, idempotency_key=keys[n])

    threads = [threading.Thread(target=call, args=(n,)) for n in range(2)]
    threads[0].start()
    read.wait()
    threads[1].start()
    while threads[1].is_alive() and _most_on_one_key() < 2:
        threads[1].join(0.001)
    second_finished = not threads[1].is_alive()
    go.set()
    for t in threads:
        t.join()
    return answers, second_finished


def test_two_calls_under_one_new_key_in_one_store_give_one_evaluation_and_one_record(tmp_path, monkeypatch):
    """Two clients of one store (two agents' clients, say, on the process's one audit file), one thread each."""
    evaluations = []
    evaluate = PolicyEvaluator.evaluate

    def counted(self, *args, **kwargs):
        evaluations.append(1)
        return evaluate(self, *args, **kwargs)

    monkeypatch.setattr(PolicyEvaluator, "evaluate", counted)
    (first, second), second_finished = _race([_client(tmp_path), _client(tmp_path)],
                                             ["idem_row160_local", "idem_row160_local"], monkeypatch)

    assert not second_finished, "the second call waited on the key"
    assert second.action_id == first.action_id, "the second call returns the first call's decision"
    assert len(evaluations) == 1, "one evaluation"
    assert len(_records(tmp_path)) == 1, "one record"
    assert AuditLogger._holds == {}, "a key no call holds or waits on is dropped"



@pytest.mark.parametrize("form", ["directory-link", "file-link", "hard-link"])
def test_one_store_reached_through_another_name_gives_one_evaluation_and_one_record(tmp_path, monkeypatch, form):
    """A store is its file, whatever name reaches it: the holds are the file's (HTL-29 review, condition 3;
    ecp_evaluate_spec.md §4, "clients of one process that share a store share its holds")."""
    evaluations = []
    evaluate = PolicyEvaluator.evaluate

    def counted(self, *args, **kwargs):
        evaluations.append(1)
        return evaluate(self, *args, **kwargs)

    monkeypatch.setattr(PolicyEvaluator, "evaluate", counted)
    first_client = _client(tmp_path)
    second_client = HIITL(audit_db_path=str(_another_name(tmp_path, form)))
    (first, second), second_finished = _race([first_client, second_client],
                                             ["idem_row160_local", "idem_row160_local"], monkeypatch)

    assert not second_finished, "the second call waited on the key"
    assert second.action_id == first.action_id, "the second call returns the first call's decision"
    assert len(evaluations) == 1, "one evaluation"
    assert len(_records(tmp_path)) == 1, "one record"
    assert AuditLogger._holds == {}, "a key no call holds or waits on is dropped"

def test_a_call_under_another_key_does_not_wait(tmp_path, monkeypatch):
    client = _client(tmp_path)
    (first, second), second_finished = _race([client, client], ["idem_row160_a", "idem_row160_b"], monkeypatch)

    assert second_finished, "the second call, under another key, finished while the first was held"
    assert second.action_id != first.action_id
    assert len(_records(tmp_path)) == 2


def test_a_call_in_another_store_does_not_wait(tmp_path, monkeypatch):
    """The holds are a store's: a client of another audit file holds its own key."""
    (first, second), second_finished = _race([_client(tmp_path), HIITL(audit_db_path=str(tmp_path / "b.db"))],
                                             ["idem_row160_local", "idem_row160_local"], monkeypatch)

    assert second_finished, "the second call, in another store, finished while the first was held"
    assert second.action_id != first.action_id
