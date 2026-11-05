"""Local, stdlib-only cleanup of dictated text (beta).

Runs on the Whisper transcript before it's typed when `cleanup = "light"`
(dictation prose only: not voice Q&A, not a resolved terminal command; see
App._transcribe_one in app.py). `clean(text, "off")` returns text unchanged.

Deliberately CONSERVATIVE: a wrong edit to someone's sentence is far worse
than a missed filler, so each rule needs strong local evidence and otherwise
leaves the text alone. Text no rule touches comes back byte-identical.

"light" rules, applied in this order:
1. Fillers: standalone um/umm/uh/uhh/uhm/er/erm, with any comma attached
   ("Um, I think" -> "I think"; "I think, uh, we should" -> "I think we
   should"). Never "uh-huh"/"uh oh"/"uh uh", "ah", "hmm", "like", "so",
   "err", all-caps "ER"/"UM", or a quoted "um". "you know" goes only when
   commas set it off mid-sentence ("It was, you know, fine").
2. Stutters: an immediately repeated small function word collapses ("the
   the", "I I", "We, we"). Words with real doubles are never touched ("that
   that", "had had", "is is", "very very", "no no", "bye bye", and see
   _STUTTER for why "you", "it", "in", "on", "to", "so", "my" are out).
3. Spoken self-corrections: "<X>, <marker> <Y>" with marker actually / wait
   / sorry / I mean / or rather / make that / make it, or "no wait"-style
   pairs. Y (1-4 words, to the end of the clause) replaces the last len(Y)
   words of X, only when both sides are clearly the same kind of thing:
   numbers, times, units ("at 2, actually 3" -> "at 3"), weekdays or months
   ("Tuesday, actually Wednesday"), capitalized names not at a sentence start
   ("to John, no wait, Sarah" -> "to Sarah"), or the same frame with one
   word swapped ("the red one, actually the blue one" -> "the blue one").
   Otherwise nothing changes ("That was, actually, quite good"), and never
   after a negation ("Not Monday, actually Tuesday" is a contrast).
4. Tidy: every edit repairs its own neighbourhood (spacing, a comma orphaned
   by a removal, ",." -> ".", the capital of a sentence whose first word
   was a filler), and a final pass fixes any such artifact the input didn't
   already contain.

The rules are English-only: given a transcript's `language` that isn't
English, the text comes back unchanged ("er" and "um" are real words in
German and Portuguese).

Not done here: turning spoken lists into bullets. Typing a newline is an
Enter key press, which sends the message in most chat apps, so list
formatting waits for per-app styles.
"""

import re

# -- tokens -------------------------------------------------------------------
# One token per whitespace-separated chunk: opening punctuation, the word,
# closing punctuation, then the whitespace after it. Rules reason about
# words; untouched tokens reassemble byte-for-byte.
_OPEN = "\"'“‘«([{¿¡"
_CLOSE = ".,;:!?\"'”’»)]}…-—–"
_QUOTES = "\"'”’»)]}"  # closers that can follow a sentence end: 'ok."'
_CLAUSE_END = re.compile(r"[.,;:!?…]+")


class _Tok:
    __slots__ = ("lead", "core", "trail", "ws")

    def __init__(self, chunk, ws):
        i, j = 0, len(chunk)
        while i < j and chunk[i] in _OPEN:
            i += 1
        while j > i and chunk[j - 1] in _CLOSE:
            j -= 1
        self.lead, self.core, self.trail = chunk[:i], chunk[i:j], chunk[j:]
        self.ws = ws

    @property
    def low(self):
        return self.core.lower().replace("’", "'")

    def __str__(self):
        return self.lead + self.core + self.trail + self.ws


def _tokenize(text):
    prefix = re.match(r"\s*", text).group()
    return prefix, [_Tok(m.group(1), m.group(2))
                    for m in re.finditer(r"(\S+)(\s*)", text)]


def _ends_sentence(tok):
    return tok.trail.rstrip(_QUOTES).endswith((".", "?", "!", "…"))


def _sentence_start(toks, i):
    return i == 0 or _ends_sentence(toks[i - 1]) or "\n" in toks[i - 1].ws


def _capitalize(tok):
    """Sentence-start capital, only for a plain lowercase word ("iPhone",
    "2pm" and "Sarah" are left alone)."""
    if tok.core[:1].islower() and tok.core == tok.core.lower():
        tok.core = tok.core[0].upper() + tok.core[1:]


def _remove(toks, i, n=1):
    """Delete toks[i:i+n] without leaving doubled or trailing spaces."""
    gone = toks[i + n - 1].ws
    del toks[i:i + n]
    if i:
        prev = toks[i - 1]
        if i == len(toks) or ("\n" in gone and "\n" not in prev.ws):
            prev.ws = gone


# -- 1. fillers ---------------------------------------------------------------
_FILLER = re.compile(r"um+|uh+m*|erm+|er")  # not "err" (a verb)
_PAUSE = (",", "...", "…")
_END = re.compile(r"[.?!]|[?!]{2,}")
# Spaced interjections that contain a filler: "uh oh", "uh huh", "uh uh".
_INTERJECTIONS = {("uh", "oh"), ("uh", "huh"), ("uh", "uh"), ("uh", "hmm"),
                  ("um", "hmm"), ("mm", "hmm")}
# Words a comma can't sensibly follow, so a comma left on one only set off
# the removed filler: "to the, uh, store" -> "to the store".
_DANGLING = set("""
    the a an this these those my your his her our their its
    to of for with at by from into onto about than
    and or but nor because if
    is are was were am be been being have has had do does did
    will would can could should shall might must
    i we they he she i'm we're they're he's she's it's you're
    very really just not
""".split())


def _comma_earlier(toks, p):
    """Is there a comma before toks[p] in its sentence (a list, an opener)?"""
    for j in range(p - 1, -1, -1):
        if _ends_sentence(toks[j]):
            return False
        if "," in toks[j].trail:
            return True
    return False


def _clause_before(toks, p):
    """The tokens of the clause that ends at toks[p], in order."""
    j = p
    while j > 0 and not _CLAUSE_END.search(toks[j - 1].trail):
        j -= 1
    return toks[j:p + 1]


def _drop_orphan_comma(toks, p, paused):
    """A filler (or "you know") was just removed after toks[p]: drop toks[p]'s
    comma when it only set the filler off ("I think, uh, we" -> "I think
    we"). Kept after a sentence's opening word ("Yes, um, I agree"), in a
    list ("eggs, milk, uh, bread"), before a correction marker, and when the
    speaker restarts ("Can you, um, can you" -> "Can you, can you")."""
    prev = toks[p]
    if not prev.trail.endswith(",") or p + 1 >= len(toks):
        return
    if (_marker_len(toks, p + 1)
            or toks[p + 1].low in {t.low for t in _clause_before(toks, p)}):
        return
    if prev.low in _DANGLING or (paused and not _sentence_start(toks, p)
                                 and not _comma_earlier(toks, p)):
        prev.trail = prev.trail[:-1]


def _is_filler(toks, i):
    t = toks[i]
    if t.lead or not _FILLER.fullmatch(t.low):
        return False
    if len(t.core) > 1 and t.core.isupper():  # "ER", "UM": acronyms
        return False
    if t.trail and t.trail not in _PAUSE and not _END.fullmatch(t.trail):
        return False  # 'um"', "um)", "um;": leave odd punctuation alone
    if (i + 1 < len(toks) and not t.trail
            and (t.low, toks[i + 1].low) in _INTERJECTIONS):
        return False
    if (i and not toks[i - 1].trail
            and (toks[i - 1].low, t.low) in _INTERJECTIONS):
        return False
    return True


def _drop_fillers(toks):
    changed = False
    i = 0
    while i < len(toks):
        if not _is_filler(toks, i):
            i += 1
            continue
        t = toks[i]
        recap = t.core[0].isupper() and _sentence_start(toks, i)
        _remove(toks, i)
        changed = True
        prev = toks[i - 1] if i else None
        nxt = toks[i] if i < len(toks) else None
        if prev is not None:
            if _END.fullmatch(t.trail):
                # "What is it, um?" -> "What is it?"
                if not _ends_sentence(prev):
                    prev.trail = prev.trail.rstrip(",;:") + t.trail
            elif nxt is None:
                # filler ended the text: "I think, um" -> "I think"
                prev.trail = prev.trail.rstrip(",;:")
                if t.trail in ("...", "…") and not prev.trail:
                    prev.trail = t.trail
            else:
                _drop_orphan_comma(toks, i - 1, paused=t.trail in _PAUSE)
        if recap and nxt is not None:
            _capitalize(nxt)  # "Um, we should" -> "We should"
        i = max(i - 1, 0)  # prev's punctuation may have changed: look again
    return changed


def _drop_you_know(toks):
    """Remove a "you know" set off by commas mid-sentence ("It was, you
    know, fine" -> "It was fine"); never at a sentence's start or end."""
    changed = False
    i = 1
    while i + 2 < len(toks):
        a, b = toks[i], toks[i + 1]
        if (a.core == "you" and b.core == "know" and not a.lead and not a.trail
                and not b.lead and b.trail == ","
                and toks[i - 1].trail.endswith(",")):
            _remove(toks, i, 2)
            _drop_orphan_comma(toks, i - 1, paused=True)
            changed = True
        else:
            i += 1
    return changed


# -- 2. stutters --------------------------------------------------------------
# Function words whose immediate repeat is almost always a stutter. Left out
# because they have real doubles: you ("told you you'd"), it ("want it it's
# yours"), in/on ("log in in Chrome", "turn it on on boot"), to ("reach out
# to to ask"), so ("so so" = mediocre), my ("my my!"), and that/had/is.
_STUTTER = {"the", "a", "an", "i", "we", "and", "but", "if",
            "of", "for", "with"}
# Can end a clause ("What's it for, for real?"), so only the comma-less
# repeat counts for these.
_STRANDABLE = {"of", "for", "with"}


def _is_stutter(toks, i):
    a, b = toks[i], toks[i + 1]
    w = a.low
    if w not in _STUTTER or b.low != w or b.lead or "\n" in a.ws:
        return False
    if a.trail and not (a.trail == "," and w not in _STRANDABLE):
        return False
    if set(a.lead) & set("\"'“‘«") and set(b.trail) & set("\"'”’»"):
        return False  # a quoted mention: 'stutters ("the the")'
    same = a.core == b.core and (b.core.islower() or b.core == "I")
    opener = (_sentence_start(toks, i) and b.core.islower()
              and a.core == b.core.capitalize())  # "The the"
    if not (same or opener):
        return False  # "The The" (a band), "A a" (the letter A)
    # "World War I, I think": a roman numeral after a capitalized word
    return not (w == "i" and i and toks[i - 1].core[:1].isupper()
                and not _sentence_start(toks, i - 1))


def _collapse_stutters(toks):
    changed = False
    i = 0
    while i + 1 < len(toks):
        if _is_stutter(toks, i):
            # keep the first's case and the second's punctuation
            a, b = toks[i], toks.pop(i + 1)
            a.trail, a.ws = b.trail, b.ws
            changed = True
        else:
            i += 1
    return changed


# -- 3. self-corrections ------------------------------------------------------
_MARKERS = (("no", "wait"), ("no", "sorry"), ("no", "actually"),
            ("wait", "no"), ("actually", "no"), ("i", "mean"),
            ("or", "rather"), ("make", "that"), ("make", "it"),
            ("actually",), ("wait",), ("sorry",))
_MAX_Y = 4
_SEPARATORS = (",", "...", "…", "—", "–")  # ends X: "X, actually Y"
_DASHES = ("-", "--", "—", "–")            # or a standalone "X - actually Y"
# Sentence context in which "X, <marker> Y" is not a slip being fixed:
# "Not Monday, actually Tuesday" contrasts (replacing would flip it),
_NEGATIONS = {"not", "no", "never", "neither", "nor", "without"}
# "When I say X, I mean Y" defines a term,
_SAY = {"say", "says", "said", "saying", "mean", "means", "meant"}
# and in "We expected 5, actually 7" "actually" means "in reality".
_BELIEF = set("expected thought estimated predicted projected guessed assumed "
              "figured believed planned budgeted hoped supposed".split())
# After a fix set off as an aside ("X, I mean Y, rest") the closing comma
# goes too, unless one of these starts a new clause or list item.
_CLAUSE_STARTERS = set("""
    i we you he she it they there this that these those
    and or but nor so then which who whose where
    because if when while although though unless until please
""".split())

_KINDS = {}
for _kind, _words in (
    ("number", "zero two three four five six seven eight nine ten eleven "
               "twelve thirteen fourteen fifteen sixteen seventeen eighteen "
               "nineteen twenty thirty forty fifty sixty seventy eighty "
               "ninety hundred thousand million billion half noon midnight "
               "first second third fourth fifth sixth seventh eighth ninth "
               "tenth"),
    ("day", "monday tuesday wednesday thursday friday saturday sunday "
            "today tomorrow tonight yesterday"),
    ("month", "january february march april may june july august september "
              "october november december"),
    ("clock", "am pm a.m p.m o'clock"),
    ("time unit", "second seconds sec secs minute minutes min mins hour hours "
                  "hr hrs day days week weeks month months year years"),
    ("money", "dollar dollars buck bucks cent cents euro euros pound pounds "
              "quid yen rupee rupees"),
):
    for _w in _words.split():
        _KINDS.setdefault(_w, set()).add(_kind)
# "one" is left out on purpose: in "this one, actually two" it's a pronoun.
_NUMBER = re.compile(
    r"[$€£]?\d+(?:[.,:/]\d+)*(?:%|st|nd|rd|th|s|k|am|pm|a\.m|p\.m)?")


def _kinds(t):
    kinds = set(_KINDS.get(t.low, ()))
    if "month" in kinds and not t.core[:1].isupper():
        kinds.discard("month")  # "may", "march" are verbs
    if _NUMBER.fullmatch(t.low):
        kinds.add("number")
    return kinds


def _is_name(t):
    c = t.core
    for ch in "'’-.":
        c = c.replace(ch, "")
    return (t.core[:1].isupper() and c.isalpha() and not _kinds(t)
            and t.low not in ("i", "i'm", "i'll", "i'd", "i've"))


def _one_marker(toks, m):
    for words in _MARKERS:
        seg = toks[m:m + len(words)]
        if (len(seg) == len(words)
                and all(not t.lead and t.low == w for t, w in zip(seg, words))
                and all(t.trail in ("", ",") for t in seg[:-1])):
            return len(words)
    return 0


def _marker_len(toks, m):
    """Number of tokens in the correction marker at toks[m] (0 if none).
    Markers chain: "sorry, I mean", "actually, no wait"."""
    n = 0
    while True:
        k = _one_marker(toks, m + n)
        if not k:
            return n
        n += k
        if toks[m + n - 1].trail not in ("", ","):
            return n


def _same_kind(toks, s0, span, ys, markers):
    """Is Y clearly a fix of the span it would replace?"""
    a, b = [t.low for t in span], [t.low for t in ys]
    if a == b:
        return False  # a repeat for emphasis ("I said no, I mean no")
    if any(t.low in _NEGATIONS or t.low.endswith("n't")
           for t in _clause_before(toks, s0)[:-1]):
        return False  # "It doesn't start at 2, actually 3"
    begin = s0
    while not _sentence_start(toks, begin):
        begin -= 1
    said = {t.low for t in toks[begin:s0]}
    if (("mean" in markers and said & _SAY)
            or (markers == ["actually"] and said & _BELIEF)):
        return False
    diffs = [(x, y) for x, y in zip(span, ys) if x.low != y.low]
    if all(_kinds(x) & _kinds(y) for x, y in diffs):
        return True  # "at 2 -> 3", "5 pm -> 6 pm", "Tuesday -> Wednesday"
    if a[0] == b[0] and len(diffs) == 1:
        return True  # one word swapped: "the red one -> the blue one"
    # Names, but not after "sorry" ("Thanks John, sorry Sarah" apologizes).
    return (markers != ["sorry"] and not _sentence_start(toks, s0)
            and all(_is_name(t) for t in span + ys))


def _correct_at(toks, m):
    """Resolve "<X>, <marker> <Y>" with the marker at toks[m]; True if done."""
    mk = _marker_len(toks, m)
    if not mk or toks[m + mk - 1].trail not in ("", ","):
        return False  # no marker, or nothing after it ("I like it, actually.")
    sep = toks[m - 1]
    if not sep.core and not sep.lead and sep.trail in _DASHES:
        x_end = m - 2
        if x_end < 0 or toks[x_end].trail:
            return False
    elif sep.core and sep.trail.endswith(_SEPARATORS):
        x_end = m - 1
    else:
        return False
    ys = []  # 1-4 words, running to the end of the clause
    for t in toks[m + mk:]:
        if t.lead or not t.core or len(ys) == _MAX_Y:
            return False
        ys.append(t)
        if t.trail:
            if not _CLAUSE_END.fullmatch(t.trail):
                return False
            break
        if "\n" in t.ws:
            break
    s0 = x_end - len(ys) + 1
    if not ys or s0 < 0:
        return False
    span = toks[s0:x_end + 1]
    if (any(t.lead or not t.core for t in span)
            or any(t.trail or "\n" in t.ws for t in span[:-1])):
        return False  # the replaced words must sit in X's last clause
    if not _same_kind(toks, s0, span, ys, [t.low for t in toks[m:m + mk]]):
        return False
    if _sentence_start(toks, s0) and span[0].core[:1].isupper():
        _capitalize(ys[0])  # "It's raining, actually it's pouring"
    del toks[s0:m + mk]  # the replaced words, the separator and the marker
    # The comma that closed the aside goes with it: "Version 3, I mean 4, has
    # the fix" -> "Version 4 has the fix" (kept before a new clause or item).
    n = s0 + len(ys)
    if (ys[-1].trail == "," and n < len(toks) and not toks[n].lead
            and toks[n].core[:1].islower()
            and toks[n].low.split("'")[0] not in _CLAUSE_STARTERS
            and not _marker_len(toks, n) and not _comma_earlier(toks, s0)):
        ys[-1].trail = ""
    return True


def _apply_corrections(toks):
    changed = False
    m = 1
    while m < len(toks):
        if _correct_at(toks, m):
            changed = True
            m = 1  # rescan: corrections can chain ("2, actually 3, sorry, 4")
        else:
            m += 1
    return changed


# -- 4. tidy ------------------------------------------------------------------
# Safety net for artifacts an edit could leave. Each is fixed only when the
# input didn't already contain it, so the speaker's own text is never touched.
_ARTIFACTS = (
    (re.compile(r"(?<=\S)[ \t]{2,}(?=\S)"), " "),     # double spaces
    (re.compile(r"[ \t]+(?=[,.;:!?](?:\s|$))"), ""),  # " ,"
    (re.compile(r",+(?=[.!?;:])"), ""),               # ",."
    (re.compile(r",{2,}"), ","),                      # ",,"
    (re.compile(r"\A(\s*)[,;:]+\s*"), r"\1"),         # leading comma
    (re.compile(r"[ \t]*[,;:]+(?=\s*\Z)"), ""),       # trailing comma
)


def _tidy(out, original):
    for pat, repl in _ARTIFACTS:
        if not pat.search(original):
            out = pat.sub(repl, out)
    return out


def clean(text: str, level: str = "light", language: str | None = None) -> str:
    """Tidy a transcript before it's typed. level "off" (or anything but
    "light") returns text unchanged, as does a non-English `language`."""
    if (level != "light" or not text
            or (language and not language.lower().startswith("en"))):
        return text
    prefix, toks = _tokenize(text)
    changed = False
    for rule in (_drop_fillers, _drop_you_know, _collapse_stutters,
                 _apply_corrections):
        changed |= rule(toks)
    if not changed:
        return text
    out = _tidy(prefix + "".join(map(str, toks)), text)
    return out if out.strip() else ""


if __name__ == "__main__":
    CASES = [
        # 1. fillers
        ("Um, I think so.", "I think so."),
        ("I think, uh, we should go.", "I think we should go."),
        ("I uh think so.", "I think so."),
        ("Um, we should go.", "We should go."),
        ("um, we should go", "we should go"),
        ("Yes, um, I agree.", "Yes, I agree."),
        ("So, um, what's next?", "So, what's next?"),
        ("What is it, um?", "What is it?"),
        ("I think, um.", "I think."),
        ("I think, um", "I think"),
        ("Um.", ""),
        ("Uh, um, er.", ""),
        ("Ummm, okay.", "Okay."),
        ("Uhm, sure thing.", "Sure thing."),
        ("Okay. Um, next item.", "Okay. Next item."),
        ("I went to the, uh, store.", "I went to the store."),
        ("We need eggs, milk, uh, bread.", "We need eggs, milk, bread."),
        ("Well, uh, I don't know, erm, maybe.", "Well, I don't know, maybe."),
        ("I think... um... we should.", "I think... we should."),
        ("Er, take him to the ER.", "Take him to the ER."),
        ("Um, iPhone sales are up.", "iPhone sales are up."),
        ("Can you, uh, send it?", "Can you send it?"),
        ("It was, you know, pretty bad.", "It was pretty bad."),
        ("I think, you know, it's fine.", "I think it's fine."),
        ("Well, you know, it's hard.", "Well, it's hard."),
        # 2. stutters
        ("I I think so.", "I think so."),
        ("The the meeting is at noon.", "The meeting is at noon."),
        ("Go to the the store.", "Go to the store."),
        ("We, we should go.", "We should go."),
        ("and and then we left", "and then we left"),
        ("It's a a big deal.", "It's a big deal."),
        ("Put it in the the the box.", "Put it in the box."),
        ("I, um, I think so.", "I think so."),
        ("I went to the, um, the store.", "I went to the store."),
        ("Can you, um, can you check?", "Can you, can you check?"),
        # 3. self-corrections
        ("Let's meet at 2, actually 3.", "Let's meet at 3."),
        ("Let's meet at 5 pm, sorry, 6 pm.", "Let's meet at 6 pm."),
        ("Call me at 5 p.m., sorry, 6 p.m. tomorrow.",
         "Call me at 6 p.m. tomorrow."),
        ("See you Tuesday, actually Wednesday.", "See you Wednesday."),
        ("Tuesday, actually Wednesday.", "Wednesday."),
        ("See you Tuesday, actually tomorrow.", "See you tomorrow."),
        ("Book it for March, I mean April.", "Book it for April."),
        ("Send it to John, no wait, Sarah.", "Send it to Sarah."),
        ("Ping Sarah, no, wait, Priya.", "Ping Priya."),
        ("I want the red one, actually the blue one.", "I want the blue one."),
        ("It's raining, actually it's pouring.", "It's pouring."),
        ("Two coffees, make that three coffees.", "Three coffees."),
        ("We need 4 chairs, or rather 5 chairs.", "We need 5 chairs."),
        ("It costs 5 dollars, I mean euros.", "It costs 5 euros."),
        ("Meet at 2, actually 3, sorry, 4.", "Meet at 4."),
        ("Meet at 2, actually 3, in the lobby.", "Meet at 3 in the lobby."),
        ("Version 3, I mean 4, has the fix.", "Version 4 has the fix."),
        ("On May 3, actually May 4, we launch.", "On May 4, we launch."),
        ("Invite Tom, actually Sarah, Anna and Bob.", "Invite Sarah, Anna and Bob."),
        ("Tomorrow, sorry, I mean today.", "Today."),
        ("We met on Tuesday the 5th, actually Wednesday the 6th.",
         "We met on Wednesday the 6th."),
        ("Call me at 2, no actually 3", "Call me at 3"),
        ("at 2, um, actually 3", "at 3"),
        ("at 2... actually 3", "at 3"),
        ("We use Python, actually Rust.", "We use Rust."),
        ("The deadline is Friday, wait, Thursday.", "The deadline is Thursday."),
        ("I'll call you Monday, wait, no, Tuesday.", "I'll call you Tuesday."),
        ("I'll be there at 5, make it 6.", "I'll be there at 6."),
        ("I can't go, actually I can go.", "I can go."),
        ("It's 5, sorry, it's 5:30.", "It's 5:30."),
    ]
    UNCHANGED = [
        # fillers: meaningful look-alikes and edge positions
        "Uh-huh, that works.", "Uh oh, I broke it.", "uh uh, don't touch that",
        "Hmm, let me think.", "Ah, I see.", "Like, I said so.",
        "To err is human.", 'He said "um" twice.', "Take him to the ER now.",
        "UM is a great school.", "You know, it's fine.", "It's fine, you know.",
        "Do you know what time it is?", "As you know, the meeting moved.",
        # stutters: legitimate doubles
        "I know that that is true.", "He had had enough.",
        "What it is is a mess.", "It's very very good.", "No no, that's wrong.",
        "Bye bye!", "Did I tell you you were right?",
        "When you see it it is obvious.", "We moved in in May.",
        "Turn it on on startup.", "Who should I reach out to to get access?",
        "The movie was so so.", "My my, what a surprise.",
        "World War I, I think, was worse.", "I got an A a week ago.",
        "I love The The.", "What's it for, for real?", 'Collapse ("the the") here.',
        # self-corrections: markers used normally, or no clear same-kind pair
        "That was, actually, quite good.", "I like it, actually.", "I mean it.",
        "Sorry, I can't make it.", "Wait, what time is it?",
        "No, actually, I think it's fine.", "Thanks John, sorry Sarah.",
        "It's red, or rather crimson.", "I have 2 kids, actually 3 dogs.",
        "John, actually Sarah is coming.", "John, no wait, Sarah.",
        "I said no, I mean no.", "When I say Tuesday, I mean Wednesday.",
        "When I say the server, I mean the database.",
        "The test passed, actually the build failed.",
        "It works, actually it works great.", "I'm sorry, I mean it.",
        "Wait, actually, never mind.", "Version 2.0, actually, shipped last week.",
        "I'll take this one, actually.", "We went to Paris, actually London was first.",
        "Not Monday, actually Tuesday.", "It doesn't start at 2, actually 3.",
        "I don't like red, actually blue.", "If you're late, make it quick.",
        "We expected 5, actually 7.", "I thought it was Tuesday, actually Wednesday.",
        # ordinary dictation
        "Hi Sarah, thanks for the update on the project.",
        "Can you send me the report by Friday?", "Let's sync at 3:30 tomorrow.",
        "The total came to $1,250.75 after tax.", "Actually, I already sent it.",
        "I mean, it's not the end of the world.", "Sorry for the late reply!",
        "Wait for me at the station.", 'She said "don\'t worry" and left.',
        "Run npm install, then npm run build.", "def foo(x): return x + 1",
        "git commit -m 'fix typo'", "that's it", "ok sounds good",
        "my number is 555 0199", "Meet me at 10 am, not 10 pm.",
        "I'll be there in 5 minutes.", "He's very, very tired.",
        "Thanks, John. Sarah will join later.",
        "We're free on Tuesday, Wednesday, and Thursday.",
        "The error says null pointer exception on line 42.",
        "Let me know if you have any questions.", "Is the ER on the second floor?",
        "The so-called fix didn't work.", "Email me at alex@example.com when done.",
        "I told you you'd love it.", "Okay, I mean, sure.", "Yeah, actually, that works.",
        "What, no wait, really?", "If it works, it works.",
        "I'm sorry, Dave, I'm afraid I can't do that.",
        "First, open the file; second, save it.", "He scored 3, then 4, then 5.",
        "Python 3.12, I mean the latest one, is required.", "lowercase, no punctuation",
        "  leading and trailing spaces  ", "multi\nline text\n", "Ünïcödé — ça va?",
    ]
    for src, want in CASES:
        got = clean(src)
        assert got == want, f"{src!r}: got {got!r}, want {want!r}"
        assert clean(got) == got, f"not idempotent: {src!r} -> {got!r}"
    for src in UNCHANGED:
        got = clean(src)
        assert got == src, f"changed {src!r} -> {got!r}"
    assert clean("Um, I think, uh, so.", "off") == "Um, I think, uh, so."
    assert clean("Er hat um 3 Uhr, um, angerufen.", language="de") == \
        "Er hat um 3 Uhr, um, angerufen."
    assert clean("Um, I think so.", language="en") == "I think so."
    assert clean("") == ""
    print(f"cleanup self-check OK ({len(CASES)} cleaned, "
          f"{len(UNCHANGED)} unchanged, 4 API)")
