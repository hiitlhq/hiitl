"""HTTP client for hosted mode ECP server communication.

Handles:
- POST /v1/evaluate with Bearer token auth; the body is the signed envelope
- POST /v1/actions/{action_id}/result, an action's result (event_format.md "The lifecycle")
- Retry with exponential backoff on transient failures (5xx, timeouts)
- Response parsing to Decision objects
- An outage answered as CONTROL_PLANE_UNAVAILABLE under the client's fail_mode, behind a circuit breaker, and
  recorded in the local store (decision_response.md "Error Handling", Example 9, "Where the error is answered"; R-0002)
- What the service could not take, held in that store and pushed before the next call (Stop B (i), row 200)
- Error mapping to SDK exceptions with helpful messages
"""

import logging
import time
from pathlib import Path
from typing import Optional

import httpx

from hiitl._version import __version__ as _SDK_VERSION
from hiitl.core.canonical import envelope_hash
from hiitl.core.error_decisions import audit_write_failed, outage
from hiitl.core.redaction import Redaction
from hiitl.core.types import Decision, DecisionType, Timing, Envelope
from hiitl.core.input_declarations import policy_shape
from hiitl.core.input_types import model_shape
from hiitl.sdk.numeric_declarations import SHAPES as NUMERIC_DECLARATIONS
from hiitl.sdk.audit import AuditLogger, settle_upload
from hiitl.sdk.circuit_breaker import CircuitBreaker
from hiitl.sdk.config import HostedModeConfig, SyncConfig
from hiitl.core.lifecycle import MESSAGES as LIFECYCLE_MESSAGES, RESULT_NUMBER_SHAPE
from hiitl.sdk.exceptions import AuditLogError, ConfigurationError, EnvelopeValidationError, LifecycleError, NetworkError, ServerError

logger = logging.getLogger(__name__)

# HTTP status codes that are retryable (transient failures)
_RETRYABLE_STATUS_CODES = {502, 503, 504, 429}
# A push's batch: the sync engine's audit_batch_size default (decision_response.md "Where the error is answered")
_PUSH_BATCH = SyncConfig.model_fields["audit_batch_size"].default

PRINCIPAL_TOKEN_HEADER = "X-Hiitl-Principal-Token"     # the hosted principal

from hiitl.core.numeric_domain import validate_numeric_domain, NumericDomainError, admitted_numbers, copy_supplied_input


def _admit_response(data, status, *, shape=None):
    """A current service body keeps the existing ServerError fallback and status."""
    try:
        validate_numeric_domain(data, shape=shape if shape is not None else policy_shape(Decision, Envelope))
    except NumericDomainError as error:
        raise ServerError(status, 'UNKNOWN_ERROR', str(error)) from error


class HostedClient:
    """HTTP client for ECP server hosted mode.

    Manages HTTP communication with the ECP server, including
    authentication, retries, and response parsing.
    """

    def __init__(self, config: HostedModeConfig, redaction: Optional[Redaction] = None):
        try:
            validate_numeric_domain(config, shape=HostedModeConfig.numeric_shape())
        except NumericDomainError as error:
            raise ConfigurationError(str(error)) from error
        self._config = config
        self._client = httpx.Client(
            base_url=config.server_url,
            timeout=config.timeout,
            follow_redirects=False,     # a redirect is the service's answer, not a hop (sync_engine.md section 8)
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json",
            },
        )
        # R-0002 "circuit breaker": the sync engine's own, at its own defaults (row 198: no setting)
        self._breaker = CircuitBreaker("hosted")
        # The local store at audit_db_path: what the service could not take, opened when the client first needs it
        # (Stop B (i)); its record takes the SDK's declaration (event_format.md §Redaction)
        self._redaction = redaction or Redaction()
        self._store: Optional[AuditLogger] = None
        # Whether the store may hold what is not yet pushed: at construction, and whenever the client holds something
        # new. A push the service answered clears it, so a refused record is not re-sent before every call.
        self._unpushed = True
        self._sequence = 0

    @classmethod
    def _from_admitted(cls, config: HostedModeConfig, redaction: Optional[Redaction] = None):
        """Consume only the settings the SDK constructor already owns and admitted."""
        with admitted_numbers():
            return cls(config, redaction)

    @property
    def breaker(self) -> CircuitBreaker:
        """The hosted breaker, whose state `status()` names (row 198)."""
        return self._breaker

    def evaluate(self, envelope: dict, *, principal_token: Optional[str] = None) -> Decision:
        """Send the envelope to the ECP server and return its Decision.

        The body is the envelope as the SDK built, signed and would record it (the evaluate implementation guide
        1.1: "The request body is the envelope"), its signature under `envelope_signature` (the security architecture
        §1.3). Its version is the envelope's own `signature_version`, inside the signed form; no header names it
        (row 171). The service verifies it over the body as sent and records the body as sent.

        Args:
            envelope: The signed envelope (hiitl.sdk.audit.envelope_record of it); it carries no principal
            principal_token: Sent in X-Hiitl-Principal-Token, verified by the server (T-130 §A7)

        An outage is the decision, never an exception (decision_response.md Error Handling: "`CONTROL_PLANE_UNAVAILABLE`
        - ECP is unreachable (circuit breaker, timeout)"): every attempt timed out, no connection, or a transient
        status on the last attempt that the service did not answer: no decision, and not the service's error format
        (docs-site/api/overview.mdx "Error format", row 145's ServerError). Each counts against the breaker, and any
        answer from the service is a success, at the one site every send passes (`_ask`); once it is open, a call is
        not sent and fails fast (Example 9). Before the envelope is sent, what the client holds is pushed; a push the
        service does not answer is the outage, with no evaluate sent behind it. The outage is recorded in the local
        store, under the client's fail_mode (Stop B).

        Returns:
            Decision object from server response, or CONTROL_PLANE_UNAVAILABLE under the client's fail_mode (BLOCK /
            AUDIT_WRITE_FAILED when its record cannot be written)

        Raises:
            ServerError: The server answered with no decision (a missing key, a 422's field list)
        """
        envelope = copy_supplied_input(envelope)
        try:
            validate_numeric_domain(envelope, shape=model_shape(Envelope))
        except NumericDomainError as error:
            raise EnvelopeValidationError(str(error), validation_errors=[str(error)]) from error
        return self._evaluate_admitted(envelope, principal_token=principal_token)

    def _evaluate_admitted(self, envelope: dict, *, principal_token: Optional[str] = None) -> Decision:
        """Send the owned envelope this call already admitted; no admission scope spans I/O."""
        body = {k: v for k, v in envelope.items() if k != "signature"}
        body["envelope_signature"] = envelope["signature"]
        headers = {}
        # A principal token rides in its header, never in the body
        if principal_token:
            headers[PRINCIPAL_TOKEN_HEADER] = principal_token

        started = time.perf_counter()
        unanswered = self._push_first()
        if not unanswered:
            response, unanswered = self._ask(body, headers=headers)
        if unanswered:
            return self._unavailable(envelope, started, *unanswered)
        return self._parse_response(response, admitted=response.status_code != 200)

    def _ask(self, body: dict, **send) -> tuple[Optional[httpx.Response], Optional[tuple]]:
        """One send, and whether the service answered it: `(response, None)` when it did, `(None, (reason, cause))`
        when it did not: every attempt timed out, no connection, or a transient status on the last attempt that the
        service did not answer (row 199). The breaker counts it here, at the one site every send passes, the pushes'
        and the call's own: an answer is a success, an outage a failure (R-0002; row 174)."""
        try:
            response = self._send_with_retry(body, **send)
        except NetworkError as e:
            unanswered = _outage_of(e)
        else:
            if not _unanswered(response):
                self._breaker.record_success()
                return response, None
            unanswered = ("CONTROL_PLANE_UNREACHABLE", f"HTTP {response.status_code}")
        self._breaker.record_failure()
        return None, unanswered

    def _unavailable(self, envelope: dict, started: float, reason: str, cause: object = None) -> Decision:
        """CONTROL_PLANE_UNAVAILABLE under the client's fail_mode, its cause the reason and its message authored; the
        cause is logged, and the decision is recorded in the local store (Stop B). The failure was counted where the
        send met it (`_ask`); a call the open breaker held back was not sent, so has no cause."""
        fail_mode = self._config.fail_mode
        logger.warning("hosted service at %s: %s (%s); %s", self._config.server_url, reason,
                       cause if cause is not None else "not sent",
                       "fail-open, the action is allowed without being evaluated" if fail_mode == "FAIL_OPEN"
                       else "fail-closed, the action is not allowed")
        decision = outage(envelope["action_id"], reason, fail_mode, self._breaker.state.value,
                          envelope_hash=envelope_hash(envelope), total_ms=(time.perf_counter() - started) * 1000)
        try:
            self._buffer().write(envelope, decision)
        except AuditLogError as e:
            # A record the store cannot write blocks, in either fail mode (Infrastructure spec 3)
            logger.error("The outage decision's record could not be written to %s (fail-closed): %s",
                         self._config.audit_db_path, e)
            return audit_write_failed(decision)
        self._unpushed = True
        return decision

    def _buffer(self) -> AuditLogger:
        """The local store at audit_db_path, opened on first use, so construction never fails on it.

        Raises:
            AuditLogError: The store cannot be opened
        """
        if self._store is None:
            self._store = AuditLogger(self._config.audit_db_path, redaction=self._redaction)
        return self._store

    def _push_first(self) -> Optional[tuple]:
        """Push what the client holds before its call is sent: the records to `POST /v1/sync/audit`, oldest first in
        batches, then each held result to its result path, oldest first (decision_response.md "Where the error is
        answered"; sync_engine.md §7, "Audit Buffer Management"). Returns the outage, `(reason, cause)`, when the breaker
        is open or the service did not answer a push; everything is then left held and nothing further is sent. The push
        that met no answer counted it against the breaker (`_ask`)."""
        if not self._breaker.allow_request():
            return ("CIRCUIT_BREAKER_OPEN",)
        if not self._unpushed:
            return None
        if not Path(self._config.audit_db_path).exists():
            self._unpushed = False  # nothing was ever held
            return None
        try:
            store = self._buffer()
            unanswered = self._push_records(store) or self._push_results(store)
        except AuditLogError as e:
            logger.warning("What the client holds in %s could not be read, so it was not pushed: %s",
                           self._config.audit_db_path, e)
            return None
        if not unanswered:
            self._unpushed = False
        return unanswered

    def _push_records(self, store: AuditLogger) -> Optional[tuple]:
        """The held records, oldest first, as the sync engine uploads and settles them (sync_engine.md §2.1). An
        accepted record is marked synced; one refused for its own content is marked refused, logged at error and not
        sent again; any other refusal stays held, logged at warning, and the drain stops (row 224)."""
        while records := store.get_unsynced(limit=_PUSH_BATCH):
            self._sequence += 1
            validate_numeric_domain(self._sequence, ('sync_sequence',), shape={'type':'integer'})
            response, unanswered = self._ask(
                {"records": records, "sdk_version": _SDK_VERSION, "sync_sequence": self._sequence},
                path="/v1/sync/audit")
            if unanswered:
                return unanswered
            if response.status_code != 200:
                code, message = _error_of(response)
                logger.warning("The hosted service refused the held audit records (HTTP %d, %s: %s); they stay held "
                               "in %s", response.status_code, code, message, self._config.audit_db_path)
                return None
            data = response.json()
            _admit_response(data, response.status_code, shape=NUMERIC_DECLARATIONS['audit_ack'])  # current acknowledgement
            if not settle_upload(store, records, data.get("errors") or [], logger) \
                    or len(records) < _PUSH_BATCH:
                return None
        return None

    def _push_results(self, store: AuditLogger) -> Optional[tuple]:
        """Each held result, oldest first. One whose decision's record is still held waits for it, so a result finds
        its decision (event_format.md "The Lifecycle"). The service's refusal is final: the result is removed and
        logged at error, naming the action and the reason."""
        waiting = store.unsynced_action_ids()
        for held in store.held_results():
            action_id, result = held["action_id"], held["execution_result"]
            if action_id in waiting:
                continue
            validate_numeric_domain(result, ('execution_result',))
            response, unanswered = self._ask(result, path=f"/v1/actions/{action_id}/result")
            if unanswered:
                return unanswered
            if response.status_code != 200:
                code, message = _error_of(response)
                if code not in LIFECYCLE_MESSAGES:
                    logger.warning("The hosted service did not take the held result of %s (HTTP %d, %s: %s); it stays "
                                   "held", action_id, response.status_code, code, message)
                    return None
                logger.error("The held result of %s was refused by the hosted service: [%s] %s; it is removed",
                             action_id, code, message)
            store.release_result(action_id, result)
        return None

    def record_result(self, action_id: str, result: dict) -> dict:
        """Send an action's result to the service and return the record that carries it.

        The service refuses as the SDK's store does (event_format.md "The lifecycle"): its refusal is raised as the
        LifecycleError it names. The same result again returns the first record, so a retried send is safe
        (Infrastructure spec 2: "idempotent state transitions"). During an outage the result is held in the local store
        and pushed before the next call; the return is `{action_id, execution_result, held: True}`, and a warning is
        logged (row 200).

        Raises:
            LifecycleError: the service did not record the result, with its reason
            ServerError: the service answered an error that is not a lifecycle refusal
            AuditLogError: the service could not take the result, and the store cannot hold it
        """
        try:
            validate_numeric_domain(result, shape=RESULT_NUMBER_SHAPE)
        except NumericDomainError as error:
            raise LifecycleError('RESULT_INVALID', str(error)) from error
        unanswered = self._push_first()
        if not unanswered:
            response, unanswered = self._ask(result, path=f"/v1/actions/{action_id}/result")
        if not unanswered:
            if response.status_code == 200:
                return response.json()  # the existing result record, as stored
            code, message = _error_of(response)
            if code in LIFECYCLE_MESSAGES:
                raise LifecycleError(code, message)
            raise ServerError(response.status_code, code, message)
        self._buffer().hold_result(action_id, result)
        self._unpushed = True
        logger.warning("hosted service at %s: %s (%s); the result of %s is held in %s and pushed before the next call",
                       self._config.server_url, unanswered[0], unanswered[1] if len(unanswered) > 1 else "not sent",
                       action_id, self._config.audit_db_path)
        return {"action_id": action_id, "execution_result": result, "held": True}

    def _send_with_retry(self, body: dict, headers: Optional[dict] = None, path: str = "/v1/evaluate") -> httpx.Response:
        """Send POST request with exponential backoff retry on transient failures."""
        last_error: Exception | None = None

        for attempt in range(self._config.max_retries + 1):
            try:
                response = self._client.post(path, json=body, headers=headers)
                if response.status_code != 200:
                    try:
                        current = response.json()
                    except ValueError:
                        current = None
                    # Parse failure is distinct from a located numeric refusal.
                    _admit_response(current, response.status_code, shape=NUMERIC_DECLARATIONS['audit_ack'] if path=='/v1/sync/audit' else None)

                # Success or non-retryable error: return immediately
                if response.status_code < 500 and response.status_code != 429:
                    return response

                # Retryable server error
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < self._config.max_retries:
                        wait = _backoff_delay(attempt)
                        logger.warning(
                            "ECP server returned %d, retrying in %.1fs (attempt %d/%d)",
                            response.status_code,
                            wait,
                            attempt + 1,
                            self._config.max_retries,
                        )
                        time.sleep(wait)
                        continue

                # Non-retryable 5xx or exhausted retries
                return response

            except httpx.TimeoutException as e:
                last_error = e
                if attempt < self._config.max_retries:
                    wait = _backoff_delay(attempt)
                    logger.warning(
                        "ECP server request timed out, retrying in %.1fs (attempt %d/%d)",
                        wait,
                        attempt + 1,
                        self._config.max_retries,
                    )
                    time.sleep(wait)
                    continue

            except httpx.ConnectError as e:
                raise NetworkError(self._config.server_url, e) from e

            except httpx.HTTPError as e:
                raise NetworkError(self._config.server_url, e) from e

        # All retries exhausted on timeout
        raise NetworkError(self._config.server_url, last_error)

    def _parse_response(self, response: httpx.Response, *, admitted=False) -> Decision:
        """The decision the response carries, on any status, or ServerError when it carries none.

        An error is a decision and keeps its HTTP status, the decision as its body (decision_response.md "Error
        Handling"; HTL-22 row 159): a 403 SIGNATURE_INVALID or a 500 POLICY_ERROR is read as the decision it is. A
        response with no decision body — a 401, a 422's field list — is ServerError."""
        try:
            data = response.json()
        except ValueError:
            data = None
        if not admitted:
            _admit_response(data, response.status_code)
        if _is_decision(data):
            # Map server timing format to SDK Timing model
            # Server returns {"total_ms": X, ...} — SDK expects ingest_ms + evaluation_ms
            raw_timing = data.get("timing", {})
            total_ms = raw_timing.get("total_ms", 0.0)
            timing = Timing(
                ingest_ms=raw_timing.get("ingest_ms", 0.0),
                evaluation_ms=raw_timing.get("evaluation_ms", total_ms),
                total_ms=total_ms,
            )

            # Every member the decision model declares reaches the caller, read from the model, never listed here
            # (row 204; R-0872: "no field is ever silently dropped"). Pydantic validates and coerces each (an error
            # dict to ErrorDetail); an absent or null member takes the model's default.
            members = {k: data[k] for k in Decision.model_fields if data.get(k) is not None}
            with admitted_numbers():
                return Decision(**{
                    **members,
                    "action_id": data.get("action_id", ""),
                    "decision": DecisionType(data["decision"]),
                    "reason_codes": data.get("reason_codes", []),
                    "policy_version": data.get("policy_version", ""),
                    "timing": timing,
                })

        raise ServerError(response.status_code, *_error_of(response))

    def close(self):
        """Close the HTTP client and release connections."""
        self._client.close()


def _error_of(response: httpx.Response) -> tuple:
    """The (code, message) an error response carries."""
    try:
        data = response.json()
    except ValueError:
        data = None
    error_code = "UNKNOWN_ERROR"
    message = f"Server returned HTTP {response.status_code}"

    if data is not None:
        # The documented error shapes (docs-site/api/overview.mdx "Error format"; HTL-20, row 145): an
        # object under `detail` with a string `error` and `message`, a 422's list of field problems, or a
        # message string. The TypeScript SDK reads the same three.
        detail = data.get("detail", data) if isinstance(data, dict) else data
        if isinstance(detail, dict):
            if isinstance(detail.get("error"), str):
                error_code = detail["error"]
            if isinstance(detail.get("message"), str):
                message = detail["message"]
        elif isinstance(detail, list):
            error_code = "VALIDATION_ERROR"
            message = "; ".join(_validation_problem(p) for p in detail) or message
        elif isinstance(detail, str):
            message = detail
    else:
        message = response.text or message

    return error_code, message


def _outage_of(e: NetworkError) -> tuple:
    """The outage a send that met no answer is: every attempt timed out, or no connection (Error Handling)."""
    reason = "CONTROL_PLANE_TIMEOUT" if isinstance(e.cause, httpx.TimeoutException) else "CONTROL_PLANE_UNREACHABLE"
    return reason, e.cause


def _unanswered(response: httpx.Response) -> bool:
    """A transient status on the last attempt, answered by something other than the service (a gateway): an outage
    (row 199, as built)."""
    return response.status_code in _RETRYABLE_STATUS_CODES and not _is_service_error(response)


def _is_service_error(response: httpx.Response) -> bool:
    """Whether the body is the service's error format: "a JSON body with a `detail` field" (docs-site/api/overview.mdx
    "Error format"), or a decision, which an error is once there is an envelope (decision_response.md "Error
    Handling"; row 159). The TypeScript SDK reads the same."""
    try:
        data = response.json()
    except ValueError:
        return False
    return isinstance(data, dict) and "detail" in data or _is_decision(data)


def _is_decision(data: object) -> bool:
    """Whether a body is a decision: a string `decision` and a boolean `allowed` (decision_response.md)."""
    return isinstance(data, dict) and isinstance(data.get("decision"), str) and isinstance(data.get("allowed"), bool)


def _backoff_delay(attempt: int) -> float:
    """Exponential backoff: 0.5s, 1s, 2s, capped at 4s."""
    return min(0.5 * (2 ** attempt), 4.0)


def _validation_problem(problem: object) -> str:
    """One entry of a 422's list as `field.path: message`."""
    if not isinstance(problem, dict):
        return str(problem)
    parts = problem.get("loc")
    loc = ".".join(str(part) for part in parts) if isinstance(parts, list) else ""
    msg = str(problem.get("msg", ""))
    return f"{loc}: {msg}" if loc else msg
