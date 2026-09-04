#audio_daw.py
"""
Real MIDI (python-rtmidi) and OSC (python-osc) control for DAWs such as
FL Studio, Ableton Live, Bitwig, etc. Requires the DAW's MIDI input / OSC
listener to be configured to receive from Jarvis (e.g. a virtual MIDI port
like loopMIDI on Windows, or Ableton's Remote Script OSC listener).
"""
import sys
import json
import time
from pathlib import Path

_NOTE_NAMES = {
    "c": 0, "c#": 1, "db": 1, "d": 2, "d#": 3, "eb": 3, "e": 4, "f": 5,
    "f#": 6, "gb": 6, "g": 7, "g#": 8, "ab": 8, "a": 9, "a#": 10, "bb": 10, "b": 11,
}


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _load_config() -> dict:
    try:
        path = _base_dir() / "config" / "api_keys.json"
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _note_to_midi(note: str) -> int | None:
    note = note.strip().lower()
    try:
        return int(note)
    except ValueError:
        pass
    if len(note) < 2:
        return None
    if note[1] in ("#", "b") and len(note) >= 3:
        name, octave = note[:2], note[2:]
    else:
        name, octave = note[:1], note[1:]
    if name not in _NOTE_NAMES or not octave.lstrip("-").isdigit():
        return None
    return (int(octave) + 1) * 12 + _NOTE_NAMES[name]


# ── MIDI (python-rtmidi) ────────────────────────────────────────────────────

_midi_out_cache = {}


def _get_midi_out(port_name: str | None):
    import rtmidi  # type: ignore

    key = port_name or "__default__"
    if key in _midi_out_cache:
        return _midi_out_cache[key]

    midi_out = rtmidi.MidiOut()
    ports = midi_out.get_ports()
    if not ports:
        raise RuntimeError(
            "No MIDI output ports found. Install/enable a virtual MIDI port "
            "(e.g. loopMIDI on Windows) so Jarvis and the DAW can share one."
        )

    if port_name:
        matches = [i for i, p in enumerate(ports) if port_name.lower() in p.lower()]
        if not matches:
            raise RuntimeError(f"No MIDI port matching '{port_name}'. Available: {ports}")
        midi_out.open_port(matches[0])
    else:
        midi_out.open_port(0)

    _midi_out_cache[key] = midi_out
    return midi_out


def midi_note(note: str, velocity: int = 100, channel: int = 0,
              duration: float = 0.3, port: str | None = None) -> str:
    try:
        pitch = _note_to_midi(note)
        if pitch is None:
            return f"Could not parse note '{note}' (use e.g. 'C4' or a MIDI number 0-127)."
        pitch = max(0, min(127, pitch))
        velocity = max(0, min(127, int(velocity)))
        channel = max(0, min(15, int(channel)))

        midi_out = _get_midi_out(port)
        midi_out.send_message([0x90 | channel, pitch, velocity])
        time.sleep(max(0.0, min(float(duration), 10.0)))
        midi_out.send_message([0x80 | channel, pitch, 0])
        return f"Sent MIDI note {note} (pitch {pitch}, vel {velocity})."
    except ImportError:
        return "python-rtmidi is not installed. Run: pip install python-rtmidi"
    except Exception as e:
        return f"MIDI note failed: {e}"


def midi_cc(controller: int, value: int, channel: int = 0, port: str | None = None) -> str:
    try:
        controller = max(0, min(127, int(controller)))
        value = max(0, min(127, int(value)))
        channel = max(0, min(15, int(channel)))
        midi_out = _get_midi_out(port)
        midi_out.send_message([0xB0 | channel, controller, value])
        return f"Sent MIDI CC {controller}={value} on channel {channel}."
    except ImportError:
        return "python-rtmidi is not installed. Run: pip install python-rtmidi"
    except Exception as e:
        return f"MIDI CC failed: {e}"


def midi_program_change(program: int, channel: int = 0, port: str | None = None) -> str:
    try:
        program = max(0, min(127, int(program)))
        channel = max(0, min(15, int(channel)))
        midi_out = _get_midi_out(port)
        midi_out.send_message([0xC0 | channel, program])
        return f"Sent MIDI program change {program} on channel {channel}."
    except ImportError:
        return "python-rtmidi is not installed. Run: pip install python-rtmidi"
    except Exception as e:
        return f"MIDI program change failed: {e}"


def midi_list_ports() -> str:
    try:
        import rtmidi  # type: ignore
        ports = rtmidi.MidiOut().get_ports()
        if not ports:
            return "No MIDI output ports available."
        return "MIDI output ports:\n" + "\n".join(f"  - {p}" for p in ports)
    except ImportError:
        return "python-rtmidi is not installed. Run: pip install python-rtmidi"
    except Exception as e:
        return f"Could not list MIDI ports: {e}"


# ── OSC (python-osc) — Ableton Live / Bitwig / VCV Rack etc. ────────────────

def osc_send(address: str, args: list, host: str | None = None, port: int | None = None) -> str:
    if not address.startswith("/"):
        return "OSC address must start with '/' (e.g. /live/song/start_playing)."
    cfg = _load_config()
    host = host or cfg.get("osc_host", "127.0.0.1")
    port = int(port or cfg.get("osc_port", 9000))

    try:
        from pythonosc.udp_client import SimpleUDPClient  # type: ignore
        client = SimpleUDPClient(host, port)
        client.send_message(address, args or [])
        return f"Sent OSC {address} {args} → {host}:{port}"
    except ImportError:
        return "python-osc is not installed. Run: pip install python-osc"
    except Exception as e:
        return f"OSC send failed: {e}"


# ── Public entry point ───────────────────────────────────────────────────────

def control_audio_daw(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
) -> str:
    """
    parameters:
        action     : midi_note | midi_cc | midi_program_change | midi_list_ports |
                     osc_send (required)
        note       : note name/number for 'midi_note', e.g. 'C4' or 60
        velocity   : MIDI velocity 0-127 (default: 100)
        controller : CC number for 'midi_cc'
        value      : CC value 0-127 for 'midi_cc'
        program    : program number for 'midi_program_change'
        channel    : MIDI channel 0-15 (default: 0)
        duration   : note-on hold time in seconds for 'midi_note' (default: 0.3)
        port       : MIDI port name substring (optional)
        address    : OSC address for 'osc_send', e.g. '/live/song/start_playing'
        args       : list of OSC arguments (optional)
        host, osc_port : OSC target (defaults from config or 127.0.0.1:9000)
    """
    params = parameters or {}
    action = params.get("action", "").lower().strip()

    if player:
        player.write_log(f"[DAW] {action}")

    try:
        if action == "midi_note":
            return midi_note(
                str(params.get("note", "")),
                velocity=int(params.get("velocity", 100)),
                channel=int(params.get("channel", 0)),
                duration=float(params.get("duration", 0.3)),
                port=params.get("port"),
            )

        if action == "midi_cc":
            return midi_cc(
                int(params.get("controller", 0)),
                int(params.get("value", 0)),
                channel=int(params.get("channel", 0)),
                port=params.get("port"),
            )

        if action == "midi_program_change":
            return midi_program_change(
                int(params.get("program", 0)),
                channel=int(params.get("channel", 0)),
                port=params.get("port"),
            )

        if action == "midi_list_ports":
            return midi_list_ports()

        if action == "osc_send":
            return osc_send(
                params.get("address", ""),
                params.get("args", []),
                host=params.get("host"),
                port=params.get("osc_port"),
            )

        return f"Unknown control_audio_daw action: '{action}'"

    except Exception as e:
        return f"control_audio_daw failed: {e}"
