import html
import json
import os
import re
import secrets
import sqlite3
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from xml.sax.saxutils import escape as xml_escape
from zoneinfo import ZoneInfo

import dateparser
from dateparser.search import search_dates
from flask import Flask, Response, abort, g, jsonify, request, session
from rapidfuzz import fuzz


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATABASE_PATH = os.path.join(BASE_DIR, "data", "dental_ai.sqlite3")
DATABASE_PATH = os.environ.get("DATABASE_PATH", DEFAULT_DATABASE_PATH)
DEFAULT_TIMEZONE = os.environ.get("DEFAULT_TIMEZONE", "Asia/Kolkata")

CLINICS: Dict[str, Dict[str, Any]] = {
    "smile": {
        "name": "SmileCraft Dental",
        "tagline": "Gentle family dentistry with same-week appointments.",
        "timezone": "Asia/Kolkata",
        "phone": "+91 98765 43210",
        "address": "12 Lake View Road, Kolkata",
        "admin_token": os.environ.get("SMILE_ADMIN_TOKEN", "smile-admin-local"),
        "brand": {
            "primary": "#0f766e",
            "accent": "#f59e0b",
            "surface": "#ffffff",
            "soft": "#ecfeff",
            "text": "#102a43",
            "muted": "#51606f",
        },
        "business_hours": {"open": 9, "close": 18},
        "services": [
            {
                "key": "cleaning",
                "label": "Dental Cleaning",
                "aliases": [
                    "cleaning",
                    "teeth cleaning",
                    "scaling",
                    "scale and polish",
                    "polishing",
                    "clean",
                ],
            },
            {
                "key": "toothache",
                "label": "Toothache Consultation",
                "aliases": [
                    "toothache",
                    "tooth pain",
                    "pain",
                    "cavity check",
                    "urgent dental visit",
                    "consultation",
                ],
            },
            {
                "key": "whitening",
                "label": "Teeth Whitening",
                "aliases": [
                    "whitening",
                    "bleaching",
                    "white teeth",
                    "teeth whitening",
                ],
            },
            {
                "key": "braces",
                "label": "Braces Consultation",
                "aliases": [
                    "braces",
                    "aligners",
                    "orthodontic consult",
                    "ortho consultation",
                    "invisalign",
                ],
            },
        ],
    },
    "bright": {
        "name": "BrightBite Dental Studio",
        "tagline": "Cosmetic, restorative, and preventive dentistry in one place.",
        "timezone": "Asia/Kolkata",
        "phone": "+91 91234 56789",
        "address": "88 Orchard Avenue, Bengaluru",
        "admin_token": os.environ.get("BRIGHT_ADMIN_TOKEN", "bright-admin-local"),
        "brand": {
            "primary": "#155eef",
            "accent": "#f97316",
            "surface": "#ffffff",
            "soft": "#eff6ff",
            "text": "#12212f",
            "muted": "#5b6b7c",
        },
        "business_hours": {"open": 9, "close": 18},
        "services": [
            {
                "key": "implant",
                "label": "Dental Implant Consultation",
                "aliases": [
                    "implant",
                    "implants",
                    "missing tooth consult",
                    "implant consultation",
                ],
            },
            {
                "key": "cleaning",
                "label": "Dental Cleaning",
                "aliases": [
                    "cleaning",
                    "teeth cleaning",
                    "scaling",
                    "scale and polish",
                ],
            },
            {
                "key": "checkup",
                "label": "Routine Checkup",
                "aliases": [
                    "checkup",
                    "check up",
                    "general exam",
                    "exam",
                    "consult",
                ],
            },
            {
                "key": "whitening",
                "label": "Teeth Whitening",
                "aliases": [
                    "whitening",
                    "bleaching",
                    "teeth whitening",
                ],
            },
        ],
    },
}

TEXT_REPLACEMENTS: Tuple[Tuple[str, str], ...] = (
    (r"\bappt\b", "appointment"),
    (r"\bappts\b", "appointments"),
    (r"\btmrw\b", "tomorrow"),
    (r"\btmr\b", "tomorrow"),
    (r"\btom\b", "tomorrow"),
    (r"\b2moro\b", "tomorrow"),
    (r"\b2morrow\b", "tomorrow"),
    (r"\b2nite\b", "tonight"),
    (r"\bfridayy\b", "friday"),
    (r"\bmon\b", "monday"),
    (r"\btues\b", "tuesday"),
    (r"\btue\b", "tuesday"),
    (r"\bwed\b", "wednesday"),
    (r"\bthu\b", "thursday"),
    (r"\bthur\b", "thursday"),
    (r"\bthurs\b", "thursday"),
    (r"\bfri\b", "friday"),
    (r"\bsat\b", "saturday"),
    (r"\bsun\b", "sunday"),
)

DATE_HINT_PATTERN = re.compile(
    r"\b(today|tomorrow|tonight|next|this|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"january|february|march|april|may|june|july|august|september|october|november|december|"
    r"\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{1,2}(?:st|nd|rd|th))\b",
    re.IGNORECASE,
)
TIME_AMPM_PATTERN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", re.IGNORECASE)
TIME_24H_PATTERN = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
TIME_BARE_PATTERN = re.compile(r"\b(?:at|around|by)?\s*(\d{1,2})\b", re.IGNORECASE)
NUMERIC_DATE_PATTERN = re.compile(r"\b\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?\b")
GREETING_PATTERN = re.compile(r"^(hi|hello|hey|good morning|good afternoon|good evening)\b", re.IGNORECASE)
RESTART_PATTERN = re.compile(r"\b(start over|restart|reset|new booking|book another)\b", re.IGNORECASE)
NAME_PATTERNS = (
    re.compile(r"\b(?:i am|i'm|im|this is|name is|my name is)\s+([a-z][a-z .'\-]{1,60})\b", re.IGNORECASE),
)


app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", secrets.token_hex(32))
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024
app.config["JSON_SORT_KEYS"] = False
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"


def ensure_data_directory() -> None:
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)


def get_timezone(clinic: Dict[str, Any]) -> ZoneInfo:
    return ZoneInfo(clinic.get("timezone", DEFAULT_TIMEZONE))


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def utc_now_iso() -> str:
    return utc_now().isoformat()


def escape_html(value: Any) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def normalize_text(text: str) -> str:
    normalized = text.lower().strip()
    for pattern, replacement in TEXT_REPLACEMENTS:
        normalized = re.sub(pattern, replacement, normalized, flags=re.IGNORECASE)
    normalized = re.sub(r"[,_]+", " ", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def normalize_identifier(value: str, max_length: int = 120) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9:+_.\-@]", "", value.strip())
    return cleaned[:max_length]


def safe_title_case_name(name: str) -> str:
    collapsed = re.sub(r"\s+", " ", name.strip(" ."))
    return " ".join(part[:1].upper() + part[1:].lower() for part in collapsed.split(" ") if part)


def format_time_label(value: str) -> str:
    hour, minute = [int(part) for part in value.split(":")]
    marker = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    return f"{display_hour}:{minute:02d} {marker}"


def format_date_label(value: str) -> str:
    parsed = datetime.strptime(value, "%Y-%m-%d").date()
    return parsed.strftime("%a, %d %b %Y")


def format_schedule_label(date_value: str, time_value: str) -> str:
    return f"{format_date_label(date_value)} at {format_time_label(time_value)}"


def serialize_timestamp(timestamp: str, tz: ZoneInfo) -> str:
    dt = datetime.fromisoformat(timestamp)
    return dt.astimezone(tz).strftime("%d %b %Y %I:%M %p").lstrip("0")


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        ensure_data_directory()
        connection = sqlite3.connect(DATABASE_PATH, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        g.db = connection
    return g.db


@app.teardown_appcontext
def close_db(_: Optional[BaseException]) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_database() -> None:
    ensure_data_directory()
    with sqlite3.connect(DATABASE_PATH) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id TEXT NOT NULL,
                channel TEXT NOT NULL,
                external_id TEXT NOT NULL,
                status TEXT NOT NULL,
                service_key TEXT,
                service_label TEXT,
                appointment_date TEXT,
                appointment_time TEXT,
                appointment_at_iso TEXT,
                patient_name TEXT,
                source_identity TEXT NOT NULL,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conversations_lookup
            ON conversations (clinic_id, channel, external_id, updated_at DESC, id DESC);

            CREATE INDEX IF NOT EXISTS idx_conversations_status
            ON conversations (clinic_id, status, updated_at DESC, id DESC);

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id TEXT NOT NULL,
                conversation_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_messages_conversation
            ON messages (clinic_id, conversation_id, id);

            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                clinic_id TEXT NOT NULL,
                conversation_id INTEGER NOT NULL UNIQUE,
                patient_name TEXT NOT NULL,
                service_key TEXT NOT NULL,
                service_label TEXT NOT NULL,
                appointment_date TEXT NOT NULL,
                appointment_time TEXT NOT NULL,
                appointment_at_iso TEXT NOT NULL,
                channel TEXT NOT NULL,
                source_identity TEXT NOT NULL,
                transcript TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_leads_clinic_created
            ON leads (clinic_id, created_at DESC, id DESC);
            """
        )


def validate_clinic_config() -> None:
    if not CLINICS:
        raise RuntimeError("At least one clinic must be configured.")
    for clinic_id, clinic in CLINICS.items():
        if not re.fullmatch(r"[a-z0-9\-]+", clinic_id):
            raise RuntimeError(f"Invalid clinic id: {clinic_id}")
        if not clinic.get("services"):
            raise RuntimeError(f"Clinic '{clinic_id}' must define at least one service.")
        for service in clinic["services"]:
            if not service.get("key") or not service.get("label"):
                raise RuntimeError(f"Clinic '{clinic_id}' has an invalid service definition.")


def get_clinic_or_404(clinic_id: str) -> Dict[str, Any]:
    clinic = CLINICS.get(clinic_id)
    if clinic is None:
        abort(404, description="Clinic not found.")
    return clinic


def get_service_index_map(clinic: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {str(index + 1): service for index, service in enumerate(clinic["services"])}


def compute_service_score(haystack: str, service: Dict[str, Any]) -> int:
    terms = {normalize_text(service["label"]), normalize_text(service["key"])}
    terms.update(normalize_text(alias) for alias in service.get("aliases", []))
    best_score = 0
    for term in terms:
        if not term:
            continue
        score = max(
            int(fuzz.token_set_ratio(haystack, term)),
            int(fuzz.partial_ratio(haystack, term)),
            int(fuzz.partial_ratio(term, haystack)),
        )
        if term in haystack:
            score = 100
        best_score = max(best_score, score)
    return best_score


def match_service(text: str, clinic: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], bool]:
    stripped = text.strip()
    service_index_map = get_service_index_map(clinic)
    if stripped in service_index_map:
        return service_index_map[stripped], False

    haystack = normalize_text(text)
    if not haystack:
        return None, False

    best_service: Optional[Dict[str, Any]] = None
    best_score = -1
    second_score = -1

    for service in clinic["services"]:
        score = compute_service_score(haystack, service)
        if score > best_score:
            second_score = best_score
            best_score = score
            best_service = service
        elif score > second_score:
            second_score = score

    ambiguous = best_score >= 78 and second_score >= 75 and abs(best_score - second_score) <= 4
    if best_service is None or best_score < 80 or ambiguous:
        return None, ambiguous
    return best_service, False


def detect_name(text: str, expecting_name: bool) -> Optional[str]:
    cleaned = text.strip()
    for pattern in NAME_PATTERNS:
        match = pattern.search(cleaned)
        if match:
            return safe_title_case_name(match.group(1))

    if expecting_name and re.fullmatch(r"[A-Za-z][A-Za-z .'\-]{1,60}", cleaned):
        return safe_title_case_name(cleaned)
    return None


def has_date_hint(text: str) -> bool:
    return bool(DATE_HINT_PATTERN.search(text))


def has_time_hint(text: str) -> bool:
    return any(
        (
            bool(TIME_AMPM_PATTERN.search(text)),
            bool(TIME_24H_PATTERN.search(text)),
            bool(re.search(r"\b(morning|afternoon|evening|noon|tonight)\b", text, re.IGNORECASE)),
            bool(re.search(r"\b(?:at|around|by)\s+\d{1,2}\b", text, re.IGNORECASE)),
            bool(re.fullmatch(r"\d{1,2}", text.strip())),
        )
    )


def choose_business_hour(hour_value: int, clinic: Dict[str, Any]) -> Optional[int]:
    hours = clinic.get("business_hours", {"open": 9, "close": 18})
    open_hour = int(hours.get("open", 9))
    close_hour = int(hours.get("close", 18))
    candidates = []
    for candidate in (hour_value, hour_value + 12 if hour_value < 12 else hour_value):
        if open_hour <= candidate <= close_hour:
            candidates.append(candidate)
    if candidates:
        return max(candidates)
    if open_hour <= hour_value <= close_hour:
        return hour_value
    return None


def extract_time_component(text: str, clinic: Dict[str, Any]) -> Optional[str]:
    ampm_match = TIME_AMPM_PATTERN.search(text)
    if ampm_match:
        hour_value = int(ampm_match.group(1))
        minute_value = int(ampm_match.group(2) or 0)
        marker = ampm_match.group(3).lower()
        if marker == "pm" and hour_value != 12:
            hour_value += 12
        if marker == "am" and hour_value == 12:
            hour_value = 0
        return f"{hour_value:02d}:{minute_value:02d}"

    time_24_match = TIME_24H_PATTERN.search(text)
    if time_24_match:
        hour_value = int(time_24_match.group(1))
        minute_value = int(time_24_match.group(2))
        return f"{hour_value:02d}:{minute_value:02d}"

    keyword_map = {
        "morning": "09:00",
        "afternoon": "14:00",
        "evening": "17:00",
        "noon": "12:00",
        "tonight": "18:00",
    }
    for keyword, mapped in keyword_map.items():
        if re.search(rf"\b{keyword}\b", text, re.IGNORECASE):
            return mapped

    bare_match = TIME_BARE_PATTERN.search(text)
    if bare_match and not NUMERIC_DATE_PATTERN.search(text):
        hour_value = int(bare_match.group(1))
        chosen = choose_business_hour(hour_value, clinic)
        if chosen is not None:
            return f"{chosen:02d}:00"
    return None


def strip_time_phrases(text: str) -> str:
    stripped = TIME_AMPM_PATTERN.sub(" ", text)
    stripped = TIME_24H_PATTERN.sub(" ", stripped)
    stripped = re.sub(r"\b(morning|afternoon|evening|noon|tonight)\b", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\b(?:at|around|by)\s+\d{1,2}\b", " ", stripped, flags=re.IGNORECASE)
    stripped = re.sub(r"\s+", " ", stripped)
    return stripped.strip()


def extract_date_component(text: str, clinic: Dict[str, Any]) -> Optional[str]:
    if not has_date_hint(text):
        return None

    timezone_name = clinic.get("timezone", DEFAULT_TIMEZONE)
    clinic_tz = get_timezone(clinic)
    reference = datetime.now(clinic_tz)
    candidate_text = strip_time_phrases(text) or text
    settings = {
        "PREFER_DATES_FROM": "future",
        "TIMEZONE": timezone_name,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "RELATIVE_BASE": reference,
    }

    matches = search_dates(candidate_text, settings=settings, languages=["en"]) or []
    for matched_text, parsed_dt in matches:
        if has_date_hint(matched_text):
            return parsed_dt.astimezone(clinic_tz).date().isoformat()

    parsed = dateparser.parse(candidate_text, settings=settings, languages=["en"])
    if parsed:
        return parsed.astimezone(clinic_tz).date().isoformat()
    return None


def combine_schedule(
    clinic: Dict[str, Any],
    existing_date: Optional[str],
    existing_time: Optional[str],
    new_date: Optional[str],
    new_time: Optional[str],
) -> Dict[str, Optional[str]]:
    appointment_date = new_date or existing_date
    appointment_time = new_time or existing_time
    appointment_at_iso: Optional[str] = None
    error: Optional[str] = None

    if appointment_date and appointment_time:
        clinic_tz = get_timezone(clinic)
        local_dt = datetime.combine(
            datetime.strptime(appointment_date, "%Y-%m-%d").date(),
            datetime.strptime(appointment_time, "%H:%M").time(),
            tzinfo=clinic_tz,
        )
        if local_dt <= datetime.now(clinic_tz):
            error = "past"
        else:
            appointment_at_iso = local_dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()

    return {
        "appointment_date": appointment_date,
        "appointment_time": appointment_time,
        "appointment_at_iso": appointment_at_iso,
        "error": error,
    }


def extract_schedule_update(text: str, clinic: Dict[str, Any], conversation: sqlite3.Row) -> Dict[str, Optional[str]]:
    normalized = normalize_text(text)
    return combine_schedule(
        clinic=clinic,
        existing_date=conversation["appointment_date"],
        existing_time=conversation["appointment_time"],
        new_date=extract_date_component(normalized, clinic),
        new_time=extract_time_component(normalized, clinic),
    )


def compute_status(payload: Dict[str, Any]) -> str:
    if payload.get("service_key") and payload.get("appointment_date") and payload.get("appointment_time") and payload.get("patient_name"):
        return "completed"
    if not payload.get("service_key"):
        return "awaiting_service"
    if not payload.get("appointment_date") or not payload.get("appointment_time"):
        return "awaiting_schedule"
    return "awaiting_name"


def get_conversation_messages(clinic_id: str, conversation_id: int) -> List[Dict[str, Any]]:
    db = get_db()
    rows = db.execute(
        """
        SELECT role, content, created_at
        FROM messages
        WHERE clinic_id = ? AND conversation_id = ?
        ORDER BY id ASC
        """,
        (clinic_id, conversation_id),
    ).fetchall()
    return [dict(row) for row in rows]


def get_latest_conversation(clinic_id: str, channel: str, external_id: str) -> Optional[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT *
        FROM conversations
        WHERE clinic_id = ? AND channel = ? AND external_id = ?
        ORDER BY id DESC
        LIMIT 1
        """,
        (clinic_id, channel, external_id),
    ).fetchone()


def get_active_conversation(clinic_id: str, channel: str, external_id: str) -> Optional[sqlite3.Row]:
    db = get_db()
    return db.execute(
        """
        SELECT *
        FROM conversations
        WHERE clinic_id = ? AND channel = ? AND external_id = ? AND status != 'completed'
        ORDER BY id DESC
        LIMIT 1
        """,
        (clinic_id, channel, external_id),
    ).fetchone()


def get_conversation_by_id(clinic_id: str, conversation_id: int) -> sqlite3.Row:
    db = get_db()
    row = db.execute(
        """
        SELECT *
        FROM conversations
        WHERE clinic_id = ? AND id = ?
        """,
        (clinic_id, conversation_id),
    ).fetchone()
    if row is None:
        raise LookupError("Conversation not found.")
    return row


def create_conversation(
    clinic_id: str,
    channel: str,
    external_id: str,
    source_identity: str,
    include_welcome: bool,
) -> sqlite3.Row:
    db = get_db()
    now = utc_now_iso()
    cursor = db.execute(
        """
        INSERT INTO conversations (
            clinic_id,
            channel,
            external_id,
            status,
            source_identity,
            created_at,
            updated_at
        )
        VALUES (?, ?, ?, 'awaiting_service', ?, ?, ?)
        """,
        (clinic_id, channel, external_id, source_identity, now, now),
    )
    conversation_id = cursor.lastrowid
    db.commit()
    conversation = get_conversation_by_id(clinic_id, int(conversation_id))
    if include_welcome:
        clinic = get_clinic_or_404(clinic_id)
        reply = compose_service_prompt(clinic, is_greeting=True)
        log_message(clinic_id, int(conversation_id), "assistant", reply)
        conversation = get_conversation_by_id(clinic_id, int(conversation_id))
    return conversation


def log_message(clinic_id: str, conversation_id: int, role: str, content: str) -> None:
    db = get_db()
    now = utc_now_iso()
    db.execute(
        """
        INSERT INTO messages (clinic_id, conversation_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (clinic_id, conversation_id, role, content, now),
    )
    db.execute(
        """
        UPDATE conversations
        SET updated_at = ?
        WHERE clinic_id = ? AND id = ?
        """,
        (now, clinic_id, conversation_id),
    )
    db.commit()


def update_conversation_fields(clinic_id: str, conversation_id: int, updates: Dict[str, Any]) -> sqlite3.Row:
    if not updates:
        return get_conversation_by_id(clinic_id, conversation_id)

    assignments = []
    values: List[Any] = []
    for key, value in updates.items():
        assignments.append(f"{key} = ?")
        values.append(value)
    assignments.append("updated_at = ?")
    values.append(utc_now_iso())
    values.extend([clinic_id, conversation_id])

    db = get_db()
    db.execute(
        f"""
        UPDATE conversations
        SET {", ".join(assignments)}
        WHERE clinic_id = ? AND id = ?
        """,
        values,
    )
    db.commit()
    return get_conversation_by_id(clinic_id, conversation_id)


def clinic_service_lines(clinic: Dict[str, Any]) -> str:
    return "\n".join(
        f"{index + 1}. {service['label']}"
        for index, service in enumerate(clinic["services"])
    )


def schedule_examples(clinic: Dict[str, Any]) -> List[str]:
    clinic_tz = get_timezone(clinic)
    tomorrow = datetime.now(clinic_tz) + timedelta(days=1)
    in_three_days = datetime.now(clinic_tz) + timedelta(days=3)
    return [
        f"Tomorrow 4 pm",
        f"{in_three_days.strftime('%A')} morning",
        tomorrow.strftime("%d %b 11:30 am"),
    ]


def compose_service_prompt(clinic: Dict[str, Any], is_greeting: bool = False, ambiguous: bool = False) -> str:
    intro = (
        f"Hi! I'm the {clinic['name']} AI receptionist. I can help you book an appointment."
        if is_greeting
        else "I can help with that."
    )
    if ambiguous:
        intro = "I found a couple of close matches."
    return (
        f"{intro}\n\n"
        f"Which service would you like?\n"
        f"{clinic_service_lines(clinic)}\n\n"
        f"You can reply with the service name or just the number."
    )


def compose_schedule_prompt(clinic: Dict[str, Any], conversation: sqlite3.Row, invalid_past: bool = False) -> str:
    examples = ", ".join(schedule_examples(clinic))
    if invalid_past:
        return f"That time looks like it has already passed. Please send a future slot, for example: {examples}."
    if conversation["appointment_date"] and not conversation["appointment_time"]:
        return (
            f"I've saved {format_date_label(conversation['appointment_date'])}. "
            f"What time works best? Examples: 10 am, 2:30 pm, 4."
        )
    if conversation["appointment_time"] and not conversation["appointment_date"]:
        return (
            f"I've saved {format_time_label(conversation['appointment_time'])}. "
            f"What date works? Examples: tomorrow, Friday, 25/05."
        )
    return f"What date and time work best? Examples: {examples}."


def compose_name_prompt(conversation: sqlite3.Row) -> str:
    schedule = format_schedule_label(conversation["appointment_date"], conversation["appointment_time"])
    return (
        f"Perfect. I have {conversation['service_label']} on {schedule}. "
        f"What name should I put on the booking?"
    )


def compose_confirmation(clinic: Dict[str, Any], conversation: sqlite3.Row) -> str:
    schedule = format_schedule_label(conversation["appointment_date"], conversation["appointment_time"])
    return (
        f"You're all set, {conversation['patient_name']}. "
        f"I've recorded your {conversation['service_label']} request for {schedule}. "
        f"The {clinic['name']} team will follow up shortly to confirm."
    )


def current_suggestions(clinic: Dict[str, Any], conversation: sqlite3.Row) -> List[str]:
    status = compute_status(dict(conversation))
    if status == "awaiting_service":
        return [service["label"] for service in clinic["services"][:4]]
    if status == "awaiting_schedule":
        return schedule_examples(clinic)
    return []


def should_restart_conversation(text: str) -> bool:
    return bool(RESTART_PATTERN.search(text))


def create_lead_if_needed(clinic_id: str, conversation: sqlite3.Row) -> None:
    if compute_status(dict(conversation)) != "completed":
        return

    db = get_db()
    existing = db.execute(
        """
        SELECT id
        FROM leads
        WHERE clinic_id = ? AND conversation_id = ?
        """,
        (clinic_id, conversation["id"]),
    ).fetchone()
    if existing:
        return

    transcript = json.dumps(get_conversation_messages(clinic_id, conversation["id"]), ensure_ascii=True)
    db.execute(
        """
        INSERT INTO leads (
            clinic_id,
            conversation_id,
            patient_name,
            service_key,
            service_label,
            appointment_date,
            appointment_time,
            appointment_at_iso,
            channel,
            source_identity,
            transcript,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            clinic_id,
            conversation["id"],
            conversation["patient_name"],
            conversation["service_key"],
            conversation["service_label"],
            conversation["appointment_date"],
            conversation["appointment_time"],
            conversation["appointment_at_iso"],
            conversation["channel"],
            conversation["source_identity"],
            transcript,
            utc_now_iso(),
        ),
    )
    db.commit()


def ensure_resume_conversation(clinic_id: str, channel: str, external_id: str, source_identity: str) -> sqlite3.Row:
    active = get_active_conversation(clinic_id, channel, external_id)
    if active is not None:
        return active

    latest = get_latest_conversation(clinic_id, channel, external_id)
    if latest is not None:
        return latest

    return create_conversation(
        clinic_id=clinic_id,
        channel=channel,
        external_id=external_id,
        source_identity=source_identity,
        include_welcome=True,
    )


def ensure_active_conversation(clinic_id: str, channel: str, external_id: str, source_identity: str) -> sqlite3.Row:
    active = get_active_conversation(clinic_id, channel, external_id)
    if active is not None:
        return active
    return create_conversation(
        clinic_id=clinic_id,
        channel=channel,
        external_id=external_id,
        source_identity=source_identity,
        include_welcome=False,
    )


def derive_reply(
    clinic: Dict[str, Any],
    conversation: sqlite3.Row,
    service_ambiguous: bool,
    schedule_error: Optional[str],
    was_greeting: bool,
) -> str:
    status = compute_status(dict(conversation))
    if service_ambiguous:
        return compose_service_prompt(clinic, ambiguous=True)
    if status == "awaiting_service":
        return compose_service_prompt(clinic, is_greeting=was_greeting)
    if status == "awaiting_schedule":
        return compose_schedule_prompt(clinic, conversation, invalid_past=(schedule_error == "past"))
    if status == "awaiting_name":
        return compose_name_prompt(conversation)
    return compose_confirmation(clinic, conversation)


def process_inbound_message(
    clinic_id: str,
    clinic: Dict[str, Any],
    channel: str,
    external_id: str,
    source_identity: str,
    raw_message: str,
) -> Dict[str, Any]:
    message = re.sub(r"\s+", " ", raw_message or "").strip()
    if not message:
        conversation = ensure_active_conversation(clinic_id, channel, external_id, source_identity)
        reply = derive_reply(clinic, conversation, service_ambiguous=False, schedule_error=None, was_greeting=False)
        log_message(clinic_id, conversation["id"], "assistant", reply)
        conversation = get_conversation_by_id(clinic_id, conversation["id"])
        return build_chat_payload(clinic_id, clinic, conversation)

    if should_restart_conversation(message):
        conversation = create_conversation(clinic_id, channel, external_id, source_identity, include_welcome=True)
        return build_chat_payload(clinic_id, clinic, conversation)

    conversation = ensure_active_conversation(clinic_id, channel, external_id, source_identity)
    log_message(clinic_id, conversation["id"], "user", message)

    updates: Dict[str, Any] = {}
    service_ambiguous = False
    schedule_error: Optional[str] = None
    was_greeting = bool(GREETING_PATTERN.search(message))
    expecting_name = compute_status(dict(conversation)) == "awaiting_name"

    matched_service, service_ambiguous = match_service(message, clinic)
    if matched_service is not None:
        updates["service_key"] = matched_service["key"]
        updates["service_label"] = matched_service["label"]

    schedule_update = extract_schedule_update(message, clinic, conversation)
    if schedule_update["error"] == "past":
        schedule_error = "past"
    else:
        if schedule_update["appointment_date"]:
            updates["appointment_date"] = schedule_update["appointment_date"]
        if schedule_update["appointment_time"]:
            updates["appointment_time"] = schedule_update["appointment_time"]
        if schedule_update["appointment_at_iso"]:
            updates["appointment_at_iso"] = schedule_update["appointment_at_iso"]
        elif "appointment_date" in updates or "appointment_time" in updates:
            updates["appointment_at_iso"] = None

    detected_name = detect_name(message, expecting_name=expecting_name)
    if detected_name:
        updates["patient_name"] = detected_name

    prospective = dict(conversation)
    prospective.update(updates)
    updates["status"] = compute_status(prospective)
    if updates["status"] == "completed":
        updates["completed_at"] = utc_now_iso()

    conversation = update_conversation_fields(clinic_id, conversation["id"], updates)
    reply = derive_reply(clinic, conversation, service_ambiguous=service_ambiguous, schedule_error=schedule_error, was_greeting=was_greeting)
    log_message(clinic_id, conversation["id"], "assistant", reply)
    conversation = get_conversation_by_id(clinic_id, conversation["id"])
    create_lead_if_needed(clinic_id, conversation)
    return build_chat_payload(clinic_id, clinic, conversation)


def build_chat_payload(clinic_id: str, clinic: Dict[str, Any], conversation: sqlite3.Row) -> Dict[str, Any]:
    messages = get_conversation_messages(clinic_id, conversation["id"])
    return {
        "clinic": {
            "id": clinic_id,
            "name": clinic["name"],
            "tagline": clinic["tagline"],
        },
        "conversation": {
            "id": conversation["id"],
            "status": compute_status(dict(conversation)),
            "service": conversation["service_label"],
            "appointment_date": conversation["appointment_date"],
            "appointment_time": conversation["appointment_time"],
            "patient_name": conversation["patient_name"],
        },
        "messages": messages,
        "suggestions": current_suggestions(clinic, conversation),
    }


def read_web_session_id() -> str:
    payload = request.get_json(silent=True) or {}
    session_id = payload.get("session_id") if request.method == "POST" else request.args.get("session_id")
    if not session_id:
        abort(400, description="session_id is required.")
    normalized = normalize_identifier(str(session_id), max_length=80)
    if not normalized:
        abort(400, description="session_id is invalid.")
    return normalized


def require_admin_access(clinic_id: str, clinic: Dict[str, Any]) -> None:
    session_key = f"admin:{clinic_id}"
    token = request.args.get("token") or request.headers.get("X-Admin-Token")
    if token and secrets.compare_digest(token, clinic["admin_token"]):
        session[session_key] = True
    if session.get(session_key):
        return
    abort(401, description="Admin token required.")


def render_root_page() -> str:
    clinic_cards = []
    for clinic_id, clinic in CLINICS.items():
        clinic_cards.append(
            f"""
            <article class="card">
              <span class="pill">{escape_html(clinic_id)}</span>
              <h2>{escape_html(clinic['name'])}</h2>
              <p>{escape_html(clinic['tagline'])}</p>
              <a href="/{escape_html(clinic_id)}">Open clinic page</a>
            </article>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Dental AI Receptionist</title>
  <style>
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      background: linear-gradient(135deg, #f8fafc 0%, #dbeafe 100%);
      color: #102a43;
      padding: 48px 24px;
      box-sizing: border-box;
    }}
    .wrap {{
      max-width: 980px;
      margin: 0 auto;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: 42px;
    }}
    p {{
      color: #51606f;
      max-width: 720px;
    }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 18px;
      margin-top: 28px;
    }}
    .card {{
      background: rgba(255,255,255,0.88);
      border: 1px solid rgba(15,23,42,0.08);
      border-radius: 22px;
      padding: 22px;
      backdrop-filter: blur(14px);
      box-shadow: 0 18px 45px rgba(15,23,42,0.08);
    }}
    .pill {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      background: #e0f2fe;
      color: #0f4c81;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
    }}
    a {{
      color: #155eef;
      font-weight: 700;
      text-decoration: none;
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <h1>Dental AI Receptionist</h1>
    <p>Every clinic lives under its own short URL, keeps isolated booking data, and shares the same production-ready booking flow across the web widget and Twilio-compatible WhatsApp webhook.</p>
    <section class="grid">
      {''.join(clinic_cards)}
    </section>
  </main>
</body>
</html>"""


def render_clinic_page(clinic_id: str, clinic: Dict[str, Any]) -> str:
    brand = clinic["brand"]
    clinic_payload = {
        "id": clinic_id,
        "name": clinic["name"],
        "tagline": clinic["tagline"],
        "services": [service["label"] for service in clinic["services"]],
        "phone": clinic["phone"],
        "address": clinic["address"],
    }
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(clinic['name'])}</title>
  <style>
    :root {{
      --primary: {escape_html(brand['primary'])};
      --accent: {escape_html(brand['accent'])};
      --surface: {escape_html(brand['surface'])};
      --soft: {escape_html(brand['soft'])};
      --text: {escape_html(brand['text'])};
      --muted: {escape_html(brand['muted'])};
      --shadow: 0 30px 80px rgba(15, 23, 42, 0.16);
      --radius: 28px;
    }}
    * {{
      box-sizing: border-box;
    }}
    body {{
      margin: 0;
      min-height: 100vh;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(255,255,255,0.95), rgba(255,255,255,0) 30%),
        linear-gradient(140deg, var(--soft) 0%, #ffffff 48%, rgba(249,115,22,0.10) 100%);
      overflow-x: hidden;
    }}
    body::before {{
      content: "";
      position: fixed;
      inset: -20vh -10vw auto auto;
      width: 40vw;
      height: 40vw;
      background: radial-gradient(circle, rgba(21, 94, 239, 0.10), rgba(21, 94, 239, 0));
      pointer-events: none;
      filter: blur(12px);
    }}
    .page {{
      max-width: 1100px;
      margin: 0 auto;
      padding: 56px 22px 140px;
      display: grid;
      gap: 26px;
    }}
    .hero {{
      background: rgba(255,255,255,0.78);
      border: 1px solid rgba(15,23,42,0.08);
      border-radius: 36px;
      padding: 34px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(16px);
      display: grid;
      gap: 18px;
    }}
    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      width: fit-content;
      background: rgba(255,255,255,0.82);
      color: var(--primary);
      font-size: 12px;
      font-weight: 800;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      border: 1px solid rgba(15,23,42,0.08);
    }}
    h1 {{
      margin: 0;
      font-size: clamp(36px, 7vw, 64px);
      line-height: 0.96;
      max-width: 12ch;
    }}
    .hero p {{
      margin: 0;
      font-size: 18px;
      line-height: 1.6;
      max-width: 56ch;
      color: var(--muted);
    }}
    .meta {{
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }}
    .meta-chip {{
      background: rgba(255,255,255,0.92);
      border-radius: 999px;
      padding: 11px 14px;
      border: 1px solid rgba(15,23,42,0.08);
      font-size: 14px;
      color: var(--text);
    }}
    .services {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
    }}
    .service-card {{
      background: linear-gradient(180deg, rgba(255,255,255,0.95), rgba(255,255,255,0.75));
      border: 1px solid rgba(15,23,42,0.08);
      border-radius: 24px;
      padding: 20px;
      box-shadow: 0 18px 36px rgba(15,23,42,0.06);
      transform: translateY(12px);
      opacity: 0;
      animation: rise 700ms ease forwards;
    }}
    .service-card:nth-child(2) {{ animation-delay: 120ms; }}
    .service-card:nth-child(3) {{ animation-delay: 220ms; }}
    .service-card:nth-child(4) {{ animation-delay: 320ms; }}
    .service-card h3 {{
      margin: 0 0 8px;
      font-size: 18px;
    }}
    .service-card p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
      font-size: 14px;
    }}
    @keyframes rise {{
      from {{
        opacity: 0;
        transform: translateY(18px);
      }}
      to {{
        opacity: 1;
        transform: translateY(0);
      }}
    }}
    .chat-launcher {{
      position: fixed;
      right: 20px;
      bottom: 20px;
      width: 64px;
      height: 64px;
      border-radius: 50%;
      border: none;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #fff;
      font-size: 26px;
      box-shadow: 0 18px 40px rgba(15,23,42,0.30);
      cursor: pointer;
      transition: transform 180ms ease, box-shadow 180ms ease;
      z-index: 30;
    }}
    .chat-launcher:hover {{
      transform: translateY(-2px) scale(1.02);
      box-shadow: 0 22px 44px rgba(15,23,42,0.34);
    }}
    .chat-panel {{
      position: fixed;
      right: 20px;
      bottom: 96px;
      width: min(380px, calc(100vw - 24px));
      height: min(72vh, 640px);
      background: #efeae2;
      border-radius: 26px;
      box-shadow: 0 34px 80px rgba(15,23,42,0.30);
      overflow: hidden;
      display: none;
      flex-direction: column;
      z-index: 40;
      border: 1px solid rgba(15,23,42,0.08);
    }}
    .chat-panel.open {{
      display: flex;
      animation: panelIn 180ms ease;
    }}
    @keyframes panelIn {{
      from {{
        opacity: 0;
        transform: translateY(14px) scale(0.98);
      }}
      to {{
        opacity: 1;
        transform: translateY(0) scale(1);
      }}
    }}
    .chat-header {{
      padding: 16px 18px;
      background: linear-gradient(135deg, var(--primary), var(--accent));
      color: #fff;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 14px;
    }}
    .chat-title {{
      display: flex;
      gap: 12px;
      align-items: center;
      min-width: 0;
    }}
    .chat-avatar {{
      width: 42px;
      height: 42px;
      border-radius: 50%;
      background: rgba(255,255,255,0.22);
      display: grid;
      place-items: center;
      font-weight: 700;
    }}
    .chat-header h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.1;
    }}
    .chat-header p {{
      margin: 3px 0 0;
      font-size: 12px;
      opacity: 0.9;
    }}
    .chat-header button {{
      background: rgba(255,255,255,0.14);
      color: #fff;
      border: none;
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
    }}
    .chat-body {{
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      background:
        radial-gradient(circle at 25% 25%, rgba(255,255,255,0.55), rgba(255,255,255,0) 22%),
        radial-gradient(circle at 80% 20%, rgba(255,255,255,0.45), rgba(255,255,255,0) 18%),
        #efeae2;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .bubble {{
      max-width: 85%;
      padding: 10px 12px;
      border-radius: 16px;
      white-space: pre-wrap;
      line-height: 1.45;
      box-shadow: 0 8px 20px rgba(15,23,42,0.08);
      font-size: 14px;
    }}
    .bubble.user {{
      align-self: flex-end;
      background: #d9fdd3;
      border-bottom-right-radius: 4px;
    }}
    .bubble.assistant {{
      align-self: flex-start;
      background: #fff;
      border-bottom-left-radius: 4px;
    }}
    .suggestions {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 0 16px 10px;
      background: #efeae2;
    }}
    .suggestion {{
      border: 1px solid rgba(15,23,42,0.12);
      background: rgba(255,255,255,0.92);
      color: var(--text);
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
      font-size: 12px;
    }}
    .chat-input {{
      background: #f5f6f6;
      padding: 12px;
      display: flex;
      gap: 10px;
      border-top: 1px solid rgba(15,23,42,0.08);
    }}
    .chat-input input {{
      flex: 1;
      border: none;
      background: #fff;
      border-radius: 999px;
      padding: 14px 16px;
      font-size: 14px;
      outline: none;
      box-shadow: inset 0 0 0 1px rgba(15,23,42,0.08);
    }}
    .chat-input button {{
      border: none;
      border-radius: 999px;
      width: 48px;
      height: 48px;
      background: var(--primary);
      color: #fff;
      font-size: 20px;
      cursor: pointer;
      flex: none;
    }}
    .chat-tools {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      padding: 0 14px 12px;
      background: #f5f6f6;
      color: var(--muted);
      font-size: 12px;
    }}
    .chat-tools a,
    .chat-tools button {{
      color: var(--primary);
      background: none;
      border: none;
      cursor: pointer;
      padding: 0;
      font: inherit;
      text-decoration: none;
    }}
    .typing {{
      align-self: flex-start;
      background: #fff;
      color: var(--muted);
    }}
    @media (max-width: 640px) {{
      .page {{
        padding-top: 30px;
      }}
      .hero {{
        padding: 24px;
        border-radius: 28px;
      }}
      .chat-panel {{
        right: 12px;
        left: 12px;
        width: auto;
        bottom: 86px;
        height: min(74vh, 640px);
      }}
      .chat-launcher {{
        right: 12px;
        bottom: 12px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <span class="eyebrow">Clinic ID /{escape_html(clinic_id)}</span>
      <h1>{escape_html(clinic['name'])}</h1>
      <p>{escape_html(clinic['tagline'])}</p>
      <div class="meta">
        <span class="meta-chip">Phone: {escape_html(clinic['phone'])}</span>
        <span class="meta-chip">Address: {escape_html(clinic['address'])}</span>
        <span class="meta-chip">WhatsApp-ready webhook included</span>
      </div>
    </section>
    <section class="services">
      {''.join(
          f"<article class='service-card'><h3>{escape_html(service['label'])}</h3><p>Book this service through the floating chat widget or the shared WhatsApp workflow.</p></article>"
          for service in clinic['services'][:4]
      )}
    </section>
  </main>

  <button class="chat-launcher" id="chat-launcher" aria-label="Open chat">💬</button>

  <section class="chat-panel" id="chat-panel" aria-live="polite" aria-label="Booking chat">
    <header class="chat-header">
      <div class="chat-title">
        <div class="chat-avatar">AI</div>
        <div>
          <h2>{escape_html(clinic['name'])}</h2>
          <p>Replies instantly • Saves your progress</p>
        </div>
      </div>
      <button type="button" id="chat-close">Close</button>
    </header>
    <div class="chat-body" id="chat-body"></div>
    <div class="suggestions" id="chat-suggestions"></div>
    <form class="chat-input" id="chat-form">
      <input id="chat-message" type="text" maxlength="500" autocomplete="off" placeholder="Type your message..." />
      <button type="submit" aria-label="Send">➤</button>
    </form>
    <div class="chat-tools">
      <span>Try: “Cleaning tomorrow 4 pm”</span>
      <button type="button" id="new-booking">New booking</button>
    </div>
  </section>

  <script>
    const clinic = {json.dumps(clinic_payload)};
    const storageKey = `dental-ai:${{clinic.id}}:session`;
    const panel = document.getElementById('chat-panel');
    const launcher = document.getElementById('chat-launcher');
    const closeButton = document.getElementById('chat-close');
    const body = document.getElementById('chat-body');
    const form = document.getElementById('chat-form');
    const input = document.getElementById('chat-message');
    const suggestions = document.getElementById('chat-suggestions');
    const newBookingButton = document.getElementById('new-booking');

    function buildSessionId() {{
      if (window.crypto && crypto.randomUUID) {{
        return crypto.randomUUID();
      }}
      return `web-${{Date.now()}}-${{Math.random().toString(16).slice(2)}}`;
    }}

    function getSessionId() {{
      let sessionId = localStorage.getItem(storageKey);
      if (!sessionId) {{
        sessionId = buildSessionId();
        localStorage.setItem(storageKey, sessionId);
      }}
      return sessionId;
    }}

    function setSessionId(sessionId) {{
      localStorage.setItem(storageKey, sessionId);
    }}

    function openPanel() {{
      panel.classList.add('open');
      launcher.style.display = 'none';
      requestAnimationFrame(() => input.focus());
    }}

    function closePanel() {{
      panel.classList.remove('open');
      launcher.style.display = 'block';
    }}

    function scrollToBottom() {{
      body.scrollTop = body.scrollHeight;
    }}

    function clearMessages() {{
      body.innerHTML = '';
    }}

    function renderMessage(role, content, isTemporary = false) {{
      const bubble = document.createElement('div');
      bubble.className = `bubble ${{role}}${{isTemporary ? ' typing' : ''}}`;
      bubble.textContent = content;
      if (isTemporary) {{
        bubble.dataset.temporary = 'true';
      }}
      body.appendChild(bubble);
      scrollToBottom();
      return bubble;
    }}

    function renderSuggestions(items) {{
      suggestions.innerHTML = '';
      if (!items || !items.length) {{
        return;
      }}
      items.forEach((item) => {{
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'suggestion';
        chip.textContent = item;
        chip.addEventListener('click', () => sendMessage(item));
        suggestions.appendChild(chip);
      }});
    }}

    function renderConversation(payload) {{
      clearMessages();
      payload.messages.forEach((message) => renderMessage(message.role, message.content));
      renderSuggestions(payload.suggestions || []);
      scrollToBottom();
    }}

    async function fetchConversation() {{
      const sessionId = getSessionId();
      const response = await fetch(`/api/${{clinic.id}}/conversation?session_id=${{encodeURIComponent(sessionId)}}`, {{
        headers: {{
          'Accept': 'application/json'
        }}
      }});
      if (!response.ok) {{
        throw new Error('Unable to load the conversation.');
      }}
      const payload = await response.json();
      renderConversation(payload);
      return payload;
    }}

    async function sendMessage(messageText) {{
      const text = String(messageText || '').trim();
      if (!text) {{
        return;
      }}

      input.value = '';
      renderMessage('user', text);
      renderSuggestions([]);
      const typingBubble = renderMessage('assistant', 'Typing…', true);

      const response = await fetch(`/api/${{clinic.id}}/message`, {{
        method: 'POST',
        headers: {{
          'Content-Type': 'application/json',
          'Accept': 'application/json'
        }},
        body: JSON.stringify({{
          session_id: getSessionId(),
          message: text
        }})
      }});

      if (typingBubble && typingBubble.parentNode) {{
        typingBubble.parentNode.removeChild(typingBubble);
      }}

      if (!response.ok) {{
        renderMessage('assistant', 'I hit a temporary issue. Please try again in a moment.');
        return;
      }}

      const payload = await response.json();
      renderConversation(payload);
    }}

    launcher.addEventListener('click', openPanel);
    closeButton.addEventListener('click', closePanel);

    form.addEventListener('submit', (event) => {{
      event.preventDefault();
      sendMessage(input.value);
    }});

    newBookingButton.addEventListener('click', async () => {{
      setSessionId(buildSessionId());
      await fetchConversation();
      input.focus();
    }});

    window.addEventListener('load', async () => {{
      openPanel();
      try {{
        await fetchConversation();
      }} catch (error) {{
        renderMessage('assistant', 'I could not load the chat just now. Please refresh and try again.');
      }}
    }});
  </script>
</body>
</html>"""


def render_admin_page(clinic_id: str, clinic: Dict[str, Any], leads: List[sqlite3.Row]) -> str:
    clinic_tz = get_timezone(clinic)
    rows = []
    for lead in leads:
        rows.append(
            f"""
            <tr>
              <td>{lead['id']}</td>
              <td>{escape_html(lead['patient_name'])}</td>
              <td>{escape_html(lead['service_label'])}</td>
              <td>{escape_html(format_schedule_label(lead['appointment_date'], lead['appointment_time']))}</td>
              <td>{escape_html(lead['channel'])}</td>
              <td>{escape_html(lead['source_identity'])}</td>
              <td>{escape_html(serialize_timestamp(lead['created_at'], clinic_tz))}</td>
            </tr>
            """
        )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape_html(clinic['name'])} Admin</title>
  <style>
    body {{
      margin: 0;
      padding: 32px 18px 60px;
      font-family: "Segoe UI", "Helvetica Neue", sans-serif;
      background: #f8fafc;
      color: #102a43;
    }}
    .wrap {{
      max-width: 1100px;
      margin: 0 auto;
    }}
    .hero {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 22px;
    }}
    h1 {{
      margin: 0;
      font-size: 34px;
    }}
    p {{
      margin: 6px 0 0;
      color: #51606f;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fff;
      border-radius: 18px;
      overflow: hidden;
      box-shadow: 0 18px 45px rgba(15,23,42,0.08);
    }}
    th, td {{
      padding: 14px 16px;
      border-bottom: 1px solid #e5e7eb;
      text-align: left;
      vertical-align: top;
      font-size: 14px;
    }}
    th {{
      background: #eef2ff;
      color: #243b53;
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    .empty {{
      background: #fff;
      border-radius: 18px;
      padding: 22px;
      color: #51606f;
      box-shadow: 0 18px 45px rgba(15,23,42,0.08);
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <section class="hero">
      <div>
        <h1>{escape_html(clinic['name'])} Leads</h1>
        <p>Clinic-scoped bookings captured by the shared receptionist workflow.</p>
      </div>
      <div>
        <strong>Clinic ID:</strong> /{escape_html(clinic_id)}
      </div>
    </section>
    {"<div class='empty'>No leads yet. Completed bookings will appear here automatically.</div>" if not rows else f"<table><thead><tr><th>ID</th><th>Name</th><th>Service</th><th>Requested Slot</th><th>Channel</th><th>Source</th><th>Captured</th></tr></thead><tbody>{''.join(rows)}</tbody></table>"}
  </main>
</body>
</html>"""


@app.after_request
def apply_response_headers(response: Response) -> Response:
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response


@app.get("/")
def home() -> str:
    return render_root_page()


@app.get("/health")
def healthcheck() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/<clinic_id>")
def clinic_page(clinic_id: str) -> str:
    clinic = get_clinic_or_404(clinic_id)
    return render_clinic_page(clinic_id, clinic)


@app.get("/api/<clinic_id>/conversation")
def get_conversation_api(clinic_id: str) -> Response:
    clinic = get_clinic_or_404(clinic_id)
    session_id = read_web_session_id()
    conversation = ensure_resume_conversation(
        clinic_id=clinic_id,
        channel="web",
        external_id=session_id,
        source_identity=session_id,
    )
    return jsonify(build_chat_payload(clinic_id, clinic, conversation))


@app.post("/api/<clinic_id>/message")
def post_message_api(clinic_id: str) -> Response:
    clinic = get_clinic_or_404(clinic_id)
    payload = request.get_json(silent=True) or {}
    session_id = normalize_identifier(str(payload.get("session_id", "")), max_length=80)
    message = str(payload.get("message", ""))
    if not session_id:
        abort(400, description="session_id is required.")
    result = process_inbound_message(
        clinic_id=clinic_id,
        clinic=clinic,
        channel="web",
        external_id=session_id,
        source_identity=session_id,
        raw_message=message,
    )
    return jsonify(result)


@app.post("/webhooks/twilio/<clinic_id>")
def twilio_webhook(clinic_id: str) -> Response:
    clinic = get_clinic_or_404(clinic_id)
    source_identity = normalize_identifier(request.form.get("WaId") or request.form.get("From") or "unknown", max_length=80)
    external_id = normalize_identifier(request.form.get("From") or source_identity, max_length=80)
    message = request.form.get("Body", "")
    payload = process_inbound_message(
        clinic_id=clinic_id,
        clinic=clinic,
        channel="whatsapp",
        external_id=external_id,
        source_identity=source_identity,
        raw_message=message,
    )
    latest_reply = payload["messages"][-1]["content"] if payload["messages"] else compose_service_prompt(clinic, is_greeting=True)
    twiml = f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{xml_escape(latest_reply)}</Message></Response>'
    return Response(twiml, content_type="application/xml; charset=utf-8")


@app.get("/<clinic_id>/admin")
def clinic_admin(clinic_id: str) -> str:
    clinic = get_clinic_or_404(clinic_id)
    require_admin_access(clinic_id, clinic)
    db = get_db()
    leads = db.execute(
        """
        SELECT *
        FROM leads
        WHERE clinic_id = ?
        ORDER BY id DESC
        """,
        (clinic_id,),
    ).fetchall()
    return render_admin_page(clinic_id, clinic, leads)


validate_clinic_config()
init_database()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=False)
