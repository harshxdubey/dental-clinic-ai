"""Creates submission/Reflections_EDIT_ME.docx - a DRAFT in the student's voice with the project facts filled in.

The yellow [ ... ] parts are about the student's FIRST hackathon and personal view: only the student can write them.
Open the .docx in Google Docs (File > Open > Upload), replace the yellow parts, then File > Download > PDF.
"""
from pathlib import Path

from docx import Document
from docx.enum.text import WD_COLOR_INDEX
from docx.shared import Pt, RGBColor

OUT = Path(__file__).resolve().parent / "Reflections_EDIT_ME.docx"
doc = Document()
st = doc.styles["Normal"]; st.font.name = "Arial"; st.font.size = Pt(10.5)
for s in ("Heading 1", "Heading 2"):
    doc.styles[s].font.name = "Arial"; doc.styles[s].font.color.rgb = RGBColor(0x13, 0x4E, 0x4A)


def para(parts, style=None):
    p = doc.add_paragraph(style=style)
    for text, hl in parts:
        r = p.add_run(text)
        if hl:
            r.font.highlight_color = WD_COLOR_INDEX.YELLOW
    return p


def fill(prompt):
    return (f"[YOUR TURN – {prompt}]", True)


doc.add_heading("Reflections: building with AI", 0)
para([("Assignment 1 – Advance track · Project: Dental Clinic AI Assistant – Pune", False)])
para([("Name: ", False), ("[your name]", True), ("   Batch/Roll no.: ", False), ("[your batch / roll no.]", True)])
para([("Yellow text = things only you can write (what you did in your first AI Hackathon, and how you feel about it). "
       "Replace each yellow part with your own words, delete this line, then download as PDF.", True)])

doc.add_heading("Where I started, and what has shifted", 1)
para([("In my first AI Hackathon I started by ", False),
      fill("1–2 sentences: what you built, what tools you used, how you worked, what you were proud of or worried about"),
      (". In this second build I wanted to make something a real clinic could depend on. The biggest shift is below, in three parts.", False)])

doc.add_heading("Reflection 1 – From “does it work?” to “how does it fail?”", 1)
para([("Then: ", False), fill("how you judged your first project – e.g. “it ran and the demo looked good”"), ("", False)])
para([("Now: I built a WhatsApp assistant for a dental clinic and, once it worked, I tested it properly instead of just demoing it. "
       "I wrote 265 test cases and, for each, wrote down what should happen before running it. The first run of messages the assistant had "
       "not been tuned on was only about 82% correct. The serious failures were not crashes: they were answers that looked fine but were wrong, "
       "such as a second question silently ignored, an unrelated stored answer sent because one word matched, and emergencies that were escalated "
       "but not flagged urgent. I found 32 problems this way. A demo would have hidden every one of them. "
       "I now treat “it runs” as the start of testing, not the end.", False)])

doc.add_heading("Reflection 2 – Let the AI help, but put the safety rules in code", 1)
para([("Then: ", False), fill("how much you trusted the AI’s output / prompts alone in the first hackathon"), ("", False)])
para([("Now: I learned that a model that writes an answer should not be the one that decides whether the answer is safe, because it can repeat its own mistake confidently. "
       "So the design splits the jobs: retrieval brings in only the clinic’s approved facts, code checks every price, doctor name and booking claim, "
       "and a single send gate refuses any unverified text. Emergencies, medical questions and appointments always go to a person. "
       "I also learned that a test that passes the first time proves little, so I deliberately broke eight of my fixes one at a time to confirm the tests noticed. "
       "Building with AI, for me, now means deciding where the AI is allowed to be uncertain and where it is not.", False)])

doc.add_heading("Reflection 3 – I am responsible for what I claim, and for reviewing what the AI builds", 1)
para([("Then: ", False), fill("how you described or reported your first project’s results"), ("", False)])
para([("Now: the AI that helped me build this also made mistakes, and two of my own fixes caused new bugs that only fresh test cases caught. "
       "Some of my first failures were mistakes in my own tests, and I reported them openly instead of hiding them. "
       "I report two numbers: about 82% correct on fresh messages, which is the honest one, and 99.6% after fixes, which is high only because I tuned the "
       "system on those same cases. I also state what I did not prove: the live WhatsApp connection and the Claude model were not tested against the real services, "
       "and all clinic data is dummy. Being clear about this mattered more to me than a bigger number.", False)])

doc.add_heading("Reflection 4 – Clear, staged instructions get better results", 1)
para([("The project grew in steps: a working prototype, then retrieval from clinic data, then answer verification, then the official WhatsApp integration, then a full quality audit. "
       "Each step had explicit rules, such as “use only the retrieved information”, “do not use unofficial WhatsApp libraries” and "
       "“do not claim it is complete until it is tested”. Those rules shaped the design more than any single clever prompt. ", False),
      fill("add 1–2 sentences about how YOUR way of asking the AI for things changed since the first hackathon"),
      ("", False)])

doc.add_heading("What I would do next", 1)
para([("Run the live WhatsApp test, replace the dummy data with the clinic’s real approved information, and start with auto-reply switched off so a receptionist approves every reply "
       "while I measure accuracy on real messages. ", False), fill("add anything else you personally want to learn or try next")])
doc.save(OUT)
print("wrote", OUT.name)
