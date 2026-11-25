import threading
from pathlib import Path

from freight_agents.agentcore.approvals import ApprovalQueue, AuditLog, IdempotencyStore


def test_the_stores_serve_threads_other_than_the_one_that_opened_them(tmp_path: Path) -> None:
    queue = ApprovalQueue(tmp_path / "approvals.sqlite3")
    done = IdempotencyStore(tmp_path / "idempotency.sqlite3")
    audit = AuditLog(tmp_path / "audit.sqlite3")
    errors: list[BaseException] = []

    def worker(n: int) -> None:
        try:
            approval = queue.request("send", {"n": n}, case_id=f"case-{n}")
            queue.approve(approval, "person")
            assert queue.use("send", {"n": n}, case_id=f"case-{n}")
            done.put(f"key-{n}", {"n": n})
            assert done.get(f"key-{n}") == {"n": n}
            audit.record(
                run_id=f"run-{n}",
                agent="a",
                case_id=f"case-{n}",
                tool="send",
                args={"n": n},
                status="ok",
                code=None,
            )
        except BaseException as exc:  # collected and asserted below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert queue.pending() == []
    assert len(audit.rows("send")) == 8
