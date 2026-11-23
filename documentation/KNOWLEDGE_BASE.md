# Adding and updating clinic information (no code needed)

Everything the assistant knows about the clinic lives in the **knowledge base**. There are three ways to change it. Pick whichever you like – they all work on the same information, every change is checked first, and **the assistant uses the change straight away** (no restart).

| Way | Best for | How |
|---|---|---|
| **1. The Knowledge Base page** | Everyday changes | http://127.0.0.1:8000/knowledge/ – forms with plain-English labels. Add, edit, delete. |
| **2. A spreadsheet (CSV)** | Updating many prices at once, or someone who prefers Excel / Google Sheets | On the Knowledge Base page: **Export CSV** → edit → **Import CSV** (you see a preview first). |
| **3. The files in `data/`** | Developers | Edit `treatments.json`, `doctors.json`, `faqs.json`, `clinic_facts.json` by hand – or use `.csv` versions of them. |

**Safety net:** a bad entry is refused with a message like *"treatment #3 (Braces): "price_min" is higher than "price_max""* instead of breaking the assistant, and before every save the previous file is copied to `data/backups/` (the last 20 are kept). To undo a change, copy a backup back over the file.

## 1. The Knowledge Base page

* **Tabs:** Treatments · Doctors · FAQs · Clinic info. Each shows the entries, with search.
* **+ Add / Edit / Delete.** Forms explain every field. Fields marked * are required.
* **Test a question** (second tab at the top): type a patient question to see what the assistant would retrieve and answer. Do this after every change.
* **Questions it couldn't answer** (right-hand side): real patient questions the knowledge base had no (full) answer to. Press **Add as FAQ** to turn one into a new FAQ – this is the best way to improve the assistant over time.
* A yellow box lists things that are allowed but probably a mistake (a treatment with no doctor assigned, a doctor who isn't listed, an FAQ with very few keywords).

### Dummy (sample) data
Every entry has a **Sample data / Real** label. When you add or edit an entry there is a checkbox *"This is sample (dummy) information"*. Tick it for made-up examples; untick it once the information is real. The patient chat and dashboard show a **"Dummy data · N entries"** badge as long as any entry is still marked as sample – it disappears when the last one is real. The shipped data is all sample data.

## 2. Spreadsheets (CSV)

Each tab has **Export CSV** and **Import CSV**. Importing **replaces the whole list** with the file, so the safest routine is: export → edit the downloaded file → import. The import shows a preview first: how many entries are new, changed or **removed** (anything not in the file is deleted), and any mistakes with row numbers. Nothing changes until you confirm.

Columns (the first row must contain these names; extra columns are ignored):

| File | Columns |
|---|---|
| treatments | `id, name, short_name, aliases, price_min, price_max, price_unit, price_notes, variants, duration, description, handled_by, dummy` |
| doctors | `id, name, title, qualification, specialties, specialty_keywords, experience_years, languages, available_days, available_hours, dummy` |
| faqs | `id, question, keywords, answer, dummy` |
| clinic | two columns: `key, value` (one row per setting) |

Writing lists and special values in a cell:

* **Lists** (`aliases`, `keywords`, `specialties`, `handled_by`, `available_days`…): separate items with ` | ` – e.g. `root canal | rct | rootcanal`.
* **variants:** `Metal braces: 30000-50000 | Ceramic braces: 50000-80000`.
* **timings** (clinic file): `Monday to Saturday = 10:00 AM to 8:00 PM | Sunday = 10:00 AM to 2:00 PM`.
* **prices:** digits only (`4000`, not `₹4,000`) – `₹` and commas are tolerated.
* **dummy:** `yes` or `no`.
* Excel's semicolon-separated CSV and UTF-8 files with a byte-order mark both work.

**Using CSV instead of JSON.** The app reads `data/<name>.json` if it exists, otherwise `data/<name>.csv`. To work from spreadsheets only, export the CSV files into `data/` and delete the `.json` ones; later edits (including those from the browser page) are saved back in the same format.

## 3. Editing the files by hand

### `clinic_facts.json`

| Field | Meaning |
|---|---|
| `clinic_name`, `short_name`, `tagline` | shown in the chat header and greeting |
| `address`, `landmark`, `maps_link`, `parking` | sent when someone asks for the location |
| `phone`, `email` | used for contact questions and in emergency, complaint and medical replies |
| `timings` | list of `{"days": "...", "hours": "..."}` – write hours like `10:00 AM to 8:00 PM` |
| `closed_note` | e.g. public-holiday closures |
| `emergency_note` | safety guidance added to emergency replies |
| `payment_methods`, `insurance_note` | answers payment and insurance questions |
| `languages` | languages the team speaks |
| `appointment_policy` | included in every booking reply |

### `treatments.json`

```json
{
  "id": "root_canal",                      // unique; lowercase letters, numbers, underscores
  "name": "Root Canal Treatment (RCT)",
  "short_name": "Root canal (RCT)",
  "aliases": ["root canal", "rct", "rootcanal"],   // what patients might type
  "price_min": 4000, "price_max": 9000,    // rupees, numbers only
  "price_unit": "per tooth",
  "price_notes": "Back teeth cost more…",
  "variants": [ {"name": "Metal braces", "price_min": 30000, "price_max": 50000} ],   // optional
  "duration": "1 to 3 visits of 45 to 60 minutes each",
  "description": "…",
  "handled_by": ["dr_rahul_kulkarni"],     // doctor ids
  "dummy": true                            // remove (or false) once the entry is real
}
```

### `doctors.json`
`id`, `name`, `title`, `qualification`, `specialties`, `specialty_keywords` (phrases like "braces doctor"), `experience_years`, `languages`, `available_days` (full day names), `available_hours` (e.g. `2:00 PM to 8:00 PM`), `dummy`.

### `faqs.json`
```json
{ "id": "walk_in", "question": "Do you accept walk-ins?",
  "keywords": ["walk in", "without appointment"],   // phrases a patient might type
  "answer": "Yes, walk-ins are welcome…", "dummy": true }
```

### `synonyms.json` (optional)
Groups of words that mean the same, so a patient who writes *cost* finds information written as *price*:
```json
{ "groups": [["price", "cost", "charge", "fee"], ["pain", "hurt", "ache", "painful"]] }
```
Add a group whenever the **Test a question** view shows a patient's word failing to match.

## Writing good entries

* **Put every number in the entry.** The assistant may only quote numbers that appear in the information it retrieved. If a price, time or phone number isn't in the knowledge base, it can't be sent – the question goes to a person instead.
* **Aliases and keywords are what find an entry.** Think of every way a patient might say it, including Hinglish (`kharcha`, `kitna`), abbreviations (`rct`) and common misspellings.
* **Write FAQ answers exactly as you want patients to read them.** The assistant repeats them, it does not improve them.
* **One fact in one place.** If the same price is in two entries and one changes, the assistant can contradict itself.
* **Don't put medical advice in FAQs** – the validator rejects drug and dosage wording, and the dentist should answer those questions.

## Before real use – checklist

- [ ] Replace every sample entry with real, current information (the badge disappears when the last sample entry is real)
- [ ] Have the clinic owner approve prices and the wording of FAQ answers, especially medical ones
- [ ] Run the tests (`python -m pytest -q`). A few assert sample values (e.g. `₹4,000` for a root canal) and will need updating – that is expected
- [ ] In **Test a question**, try your 30 most common real WhatsApp questions and note which are forwarded; add aliases, keywords, FAQs or synonyms for them
- [ ] Add the questions you *can't* answer yet as FAQs, or decide they should always go to a person
