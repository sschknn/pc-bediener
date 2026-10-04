# -*- coding: utf-8 -*-
"""Test: FLP von Grund auf mit pyflp erstellen."""
import sys
import pyflp
from pyflp._events import EventTree
from pyflp.project import Project
from pyflp.channel import Sampler
from pyflp.pattern import Pattern

p = Project(EventTree())
print("channels:", type(p.channels))
print("patterns:", type(p.patterns))
print("arrangements:", type(p.arrangements))
print("version:", repr(p.version))
print("ppq:", repr(p.ppq))
print("tempo:", repr(p.tempo))
print("title:", repr(p.title))
print("looped:", repr(p.looped))

# Was kann man setzen?
try:
    p.ppq = 96
    print("ppq set ->", p.ppq)
except Exception as e:
    print("ppq set FAILED:", e)

try:
    p.tempo = 155.0
    print("tempo set ->", p.tempo)
except Exception as e:
    print("tempo set FAILED:", e)

try:
    p.title = "Test"
    print("title set ->", p.title)
except Exception as e:
    print("title set FAILED:", e)

# Channel erzeugen
try:
    s = Sampler(EventTree())
    print("Sampler attrs:", [a for a in dir(s) if not a.startswith("_")])
    s.name = "Kick"
    print("sampler name ->", s.name)
    print("sample_path prop:", hasattr(s, "sample_path"))
    try:
        s.sample_path = r"C:\Program Files\Image-Line\FL Studio 2026\Data\Patches\Packs\Drums\Kicks\909 Kick.wav"
        print("sample_path ->", s.sample_path)
    except Exception as e:
        print("sample_path FAILED:", e)
    p.channels.append(s)
    print("channels count ->", len(p.channels))
except Exception as e:
    print("channel FAILED:", type(e).__name__, e)

# Pattern erzeugen
try:
    pat = Pattern(EventTree())
    pat.name = "P1"
    print("pattern attrs:", [a for a in dir(pat) if not a.startswith("_")])
    p.patterns.append(pat)
    print("patterns count ->", len(p.patterns))
except Exception as e:
    print("pattern FAILED:", type(e).__name__, e)

# Note erzeugen - wie?
from pyflp.pattern import Note, NotesEvent
import inspect
print("Note sig:", inspect.signature(Note.__init__))
print("Note attrs:", [a for a in dir(Note) if not a.startswith("_")])
