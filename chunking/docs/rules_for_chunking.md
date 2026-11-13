# Rules for chunking

How we turn **parsed documents** into **chunks**. This is the single rulebook for the chunking
layer. Every rule here was discussed and agreed. If a rule changes, change it here first, then
change the code and the tests.

- **Input:** the parsed documents in `data/parsed/` (one JSON file per document).
- **Output:** a list of chunks per document. Later layers (enrichment, indexing) work on chunks.
- **Format:** the rules were checked on Markdown. They work on the *shape* of a parsed document
  (sections and blocks), so they should carry over to other formats. We will add notes for other
  formats only when they come up.

---

## 1. Words used in this document

| Word | Meaning |
|---|---|
| **Block** | One piece of a parsed document: a paragraph, list, table, quote, code or HTML block. |
| **Section** | A heading and everything under it. A section holds blocks and sub-sections. |
| **Untitled section** | A section with no title. It is made when a `---` divider is followed by content. |
| **Chunk** | The unit we search. It is one block, or a few blocks merged by the rules below. |
| **Path** | The titles of the sections a chunk sits under, from the outside in. |
| **Location** | Where a block came from: its line, plus the heading right above it. |

How examples are written below: `[paragraph]`, `[list]` and so on show a block and its type.
Examples are simplified from real documents unless they say otherwise.

---

## 2. The steps, in order

1. **Start:** every block is its own chunk.
2. **Colon rule:** a line ending with a colon joins the block below it.
3. **Note and quote rule:** a note or quote joins the block above it.
4. **Small rule:** a chunk that is still very small joins the block below it.
5. **Write the text** of each chunk (lists and tables are turned into text).
6. **Fill in the fields** of each chunk (path, locations, id and so on).

The order of steps 2 to 4 matters. Merging only ever happens between **neighbours in reading
order**.

---

## 3. Starting point

### Rule 1: one block is one chunk

Every block starts as its own chunk. A list is one block, so it stays whole. A table is one block,
so it stays whole.

```
[paragraph] Charging tips
[list]      Use the USB-C cable | Charge for 15 minutes
→ 2 chunks before any merging
```

### Rule 2: a section with no blocks makes no chunk

A heading with nothing directly under it has no text to search, so it makes no chunk. Its title is
not lost: it appears in the **path** of the chunks below it.

```
Aventro Motors Pvt. Ltd.            (no blocks)
  Pre-Owned Certified Cars          (no blocks)
    Why Choose Us                   [paragraph] When you choose a pre-owned car...
→ 1 chunk, with the path:  Aventro Motors Pvt. Ltd. > Pre-Owned Certified Cars > Why Choose Us
```

### Rule 3: every chunk has a path

The path is the ordered list of the titles of the sections above the chunk, from the outermost to
the closest. An untitled section adds nothing to the path. The path is kept as its own field. Later
it is also placed at the top of the text that gets embedded, so it helps search.

```
Velvera Audio Series — Usage Guide
  Velvera Buds
    [list] Tap once: Play/Pause
→ path: Velvera Audio Series — Usage Guide > Velvera Buds
```

---

## 4. Merge rules

**Scope.** Merging stays inside one section. There is exactly one exception, the quote rule across
a `---` divider (rule 5c).

**One neighbour at a time.** A block only ever merges with the one block directly above or directly
below it. A chunk that has already merged can take part in the next step as one chunk.

### Rule 4: colon rule (join the block below)

A paragraph that **ends with a colon** introduces what comes next, so it joins the block **below**
it in the same section.

- It applies at **any length**, from a one-word label to a long sentence.
- If nothing is below it in its section, it **stays alone**. It is not merged into its sub-sections
  (see example B).
- **Guard:** it takes **one** block below and stops. The merged chunk is not checked again, so a
  colon line can never start a chain that swallows the whole section. (In our Markdown data a colon
  line is never directly followed by another colon line.)

**A. A label and its list**

```
Section: Velvera Buds
  [paragraph] Controls:
  [list]      Tap once: Play/Pause | Tap twice: Skip to next track

→ 1 chunk, text:
Controls:
- Tap once: Play/Pause
- Tap twice: Skip to next track
```

**B. Nothing below it in its section**

```
Section: How to Cancel Your Booking
  [paragraph] You can cancel your booking in two convenient ways:
  Sub-section: 1. Website            ...
  Sub-section: 2. Mobile App         ...

→ the paragraph stays a chunk of its own.
→ the sub-section chunks have the path  How to Cancel Your Booking > 1. Website  (and > 2. Mobile App),
  so a search for them still finds the right place.
```

### Rule 5: note and quote rule (join the block above)

A **note** adds to what came before, so it joins the block **above** it.

A note is either:
- a **quote block**, or
- a **paragraph that starts with `Note`, `Disclaimer` or `Important`** and is a full sentence. (A
  paragraph that ends with a colon is a label. The colon rule handles it.)

**5a. Same section.** A note or quote joins the block above it in the same section.

```
Section: Baggage Allowance
  [table] Class | Bags | Max weight ...
  [quote] Bags over 158 cm in total size may cost extra.

→ 1 chunk: the table, then the quote.
```

**5b. First block of a titled section.** It **stays alone**. Merging it into the block above would
hide that section's real title and make the path unclear.

```
Section: Warranty Coverage
  Sub-section: Claim Process        (a titled section)
    [paragraph] Note: claims need a receipt.     ← first block of a titled section

→ stays a chunk of its own, with the path  Warranty Coverage > Claim Process
```

**5c. The exception: a quote that starts an untitled section.** A `---` divider can split one topic
into two sections. A quote that is the first block of that untitled section joins the **last chunk
of the section above**, across the divider. The merged chunk keeps the path of the block above.

```
Section: Inbound Flights: Canada to Mumbai
  [table] Flight | Departure | Arrival ...
--- (divider)
Untitled section
  [quote] Note: All timings are approximate and may vary seasonally.

→ 1 chunk: the table, then the note.
→ path: Mumbai Inbound & Outbound Flights > Inbound Flights: Canada to Mumbai
```

Only a **quote** crosses a divider. A note written as a plain paragraph does not.

**Guard.** A chunk takes **at most one** note or quote through this rule. A second note or quote in
a row stays alone.

```
[list]  ATM list
[quote] First note        → joins the list
[quote] Second note       → stays alone (the list chunk already took one)
```

### Rule 6: small rule (join the block below)

A chunk with **fewer than 10 words** joins the block **below** it in the same section. If it is
still under 10 words, it keeps joining the next block until it reaches 10 words or nothing is left
below.

- Words are counted on the **content** of the blocks (the list items, table cells and paragraph
  text), not on the dashes and labels we add when writing the text.
- If nothing is below it in its section, it **stays alone**.
- The number **10 is a starting value**. We tune it by testing retrieval (see section 9).

```
Section: Pricing
  [paragraph] Starts at 20 lakh.                 (4 words)
  [list]      Petrol | Diesel | Electric | Hybrid ... (20 words)
→ 1 chunk: the 4-word line joined the list.

Section: Closing
  [paragraph] Drive safe with Aventro!           (4 words)
→ nothing below it in its section, so it stays alone.
```

---

## 5. Writing the text of a chunk

Blocks are stored as structure (a list has items, a table has rows). The chunk builder turns each
block into plain text when it builds the chunk. The parsed files are **not** rewritten. The blocks
of a merged chunk are written one after another, each on its own line.

### Paragraphs and quotes

Written as they are.

### Lists

- Each item is **one line starting with a dash**.
- If an item has a **line break** inside it, the first line is the main point. Each later line
  becomes an **indented sub-point** under it.
- Items that are **nested** in the source stay indented, one level per depth. Nested items **always
  use a dash**.
- A **numbered** list gets its numbers back: `1.`, `2.`, `3.` in order. Only top-level items are
  numbered. (The parsed file keeps only that the list is numbered, not the numbers. All numbered
  lists in our Markdown start at 1, so counting from 1 is always right.)
- An empty item is skipped.

```
Stored:  bullets, one item with a line break inside
         "Automatic Speed Regulation\nKeeps the car at a set speed"
Written:
- Automatic Speed Regulation
  - Keeps the car at a set speed
```

```
Stored:  bullets with a nested item
         "Same-Day Repairs for eligible issues such as:"   (depth 0)
         "Screen replacement"                              (depth 1)
Written:
- Same-Day Repairs for eligible issues such as:
  - Screen replacement
```

```
Stored:  numbered list, items "Register the complaint", "Upload the receipt"
Written:
1. Register the complaint
2. Upload the receipt
```

### Tables

- Each row is **one line starting with a dash**.
- A row is written as **`Label: value` pairs separated by ` | `**, using the column names from the
  header.
- There is **no separate header line**: every row carries its own labels.
- The separator is ` | ` and not `;`, because some cell values contain semicolons. No cell contains
  a `|`.
- An **empty cell stays empty**. The pair is written as `Label: ` with nothing after it. We never
  fill a blank from the row above, so no data is invented.

Real example (`aventro aero`, section *Aero Model Variants & Prices*). In the source, the fuel type
is written once and the cells below it are blank:

```
- Variant: Petrol | Trim: Base | Price (Lakh ₹): 6.5
- Variant:  | Trim: X | Price (Lakh ₹): 7.0
- Variant:  | Trim: ZX | Price (Lakh ₹): 7.5
```

### Code and raw HTML blocks

Not discussed yet. See section 10.

---

## 6. What we do not do

- **No overlap between chunks.** Overlap only matters when long text is cut in pieces. Our chunks
  follow blocks, and the largest Markdown block is 266 words, so nothing is cut. There is no
  overlap setting.
- **A list or a table is never split.** The limit on chunk size is in section 7.
- **Never merge across a titled section.** The only exception is rule 5c.
- **Never drop a block.** Small blocks are merged into a neighbour, not removed, because even a
  few words can hold useful information.

---

## 7. Size and the token budget

### Rule 7: a chunk stays within about 1,500 tokens

- **What the 1,500 covers.** Everything that is embedded for a chunk in the vector index: the path,
  the chunk text and, later, the summary and the questions that the enrichment layer adds. (The
  keywords go to the keyword index, which has no token limit.) We expect about 150 to 250 tokens
  for the path, summary and questions, so the chunk **text** itself should stay under about
  **1,200 tokens**.
- **It is a ceiling, not a target.** Most chunks are far smaller. The median block is about 50 to
  70 tokens of text.
- **How tokens are counted.** With the tokenizer of the embedding model we choose. Every embedding
  model comes with its own tokenizer, so choosing the model chooses the tokenizer. The answering
  model has a different tokenizer, used only for the size of its prompt.
- **Where we are today.** No Markdown chunk reaches the ceiling. The largest is a table in
  `store_locations`: 527 words once written out, about 850 to 1,150 tokens of text. About 160 blocks
  may be over 256 tokens, about 29 over 512, and about 1 over 1,024. (These are estimates from
  characters, at 3 to 4 per token. They are not counted with a real tokenizer yet.)
- **If a chunk goes over.** Not decided. Nothing goes over today. One option is to split a big
  table between rows and repeat the labels.

### Why 1,500

1. **It fits our data with room to spare.** The largest text plus the extra fields comes to about
   1,000 to 1,300 tokens, so 1,500 leaves a margin.
2. **The embedding model must accept it.** The model's input limit has to be at least 1,500 tokens.
   A model with a 512-token limit would cut off our longest chunks. BGE-M3, our candidate, accepts
   up to 8,192 tokens.
3. **The answer prompt still fits.** The final prompt holds the top 5 chunks plus instructions. In
   the worst case that is 5 x 1,500 = 7,500 tokens, plus about 2,500 for the instructions, so about
   10,000, and about 11,000 with the model's answer. That is far below the context window of a good
   7B model (Qwen2.5-7B-Instruct has 32K by default and 128K with a setting). In practice the prompt
   is much smaller, because the median chunk is tiny.
4. **Short chunks are not a problem.** A vector has the same size whatever the length of the input.
   A short chunk is weak only because it holds little information, which is why we merge small
   chunks and add the path and the enrichment. One caution: for a small chunk, the added summary and
   questions can be bigger than the chunk's own text, so the enrichment should stay short.

### How we will check it later

The 1,500-token ceiling is a starting plan. Later we run the pipeline with **different embedding
models**, using chunks of this size, and compare retrieval on the benchmark questions. That shows
which model works best at this size. If the results show that very long chunks hurt, we lower the
ceiling or split big tables by row.

---

## 8. What each chunk stores

| Field | What it holds |
|---|---|
| `id` | A unique name: `<doc_id>_<number>`. The number counts the chunks of the document from 1, in reading order. |
| `text` | The chunk text, written by the rules in section 5. |
| `path` | The list of section titles (rule 3). For a merged chunk, the path of its **first** block. |
| `doc_key` | The document name, as in the registry. |
| `company` | The company the document belongs to. |
| `format` | The format of the source file (`md` for now). |
| `locations` | One entry per block in the chunk: the line, plus the heading right above it. |

A merged chunk uses the path of its **first block** and keeps the location of **every** block in
it, so an answer can always point back to the exact lines.

```
id:        <doc_id>_7
text:      Controls:
           - Tap once: Play/Pause
           - Tap twice: Skip to next track
path:      Velvera Audio Series — Usage Guide > Velvera Buds
doc_key:   audio_usage_guide
company:   Velvera Technologies
format:    md
locations: line 14 (the label), line 15 (the list)
```

The **enrichment** layer adds more fields later (a summary, questions, keywords). They are not part
of chunking.

---

## 9. Settings we can tune

These can be changed and tested against the benchmark questions. Change one at a time.

| Rule | Setting | Now | What we could test |
|---|---|---|---|
| Colon | Rule on or off | on | off |
| Colon | Length cap | none | e.g. only up to 20 words |
| Note and quote | Words that mark a note | Note, Disclaimer, Important | add Tip, Warning, Caution |
| Note and quote | Merge a quote across a `---` | on | off, or only for notes |
| Small | Word cutoff | 10 | 5, 15, 20, 40 |
| Small | Direction | down | up |
| Small | Merge with neighbouring sections | off | on |
| Text | Table style | labels in every row | header once, plain rows |
| Size | Token ceiling per chunk | 1,500 tokens | 1,024 or 2,048, or splitting big tables by row |
| Size | Embedding model (which brings its tokenizer) | not chosen | BGE-M3 and others, compared on the benchmark |

---

## 10. Not decided yet

- **Code blocks and raw HTML blocks:** how they are written out. Our plan is to keep their text as
  it is. This is rare in our data.
- **The small-chunk cutoff:** 10 words is a starting value, to be tuned.
- **The embedding model:** it decides the tokenizer. The 1,500-token ceiling is set (section 7), but
  which model we use is not.
- **Other formats:** PDF, DOCX, PPTX and HTML are planned to go through Docling. Their parsed
  output must be mapped to the same sections, blocks and locations. Then these rules apply as they
  are. A format may need a rule of its own, for example slides.

---

## 11. Reference numbers on our Markdown data

Measured on 2026-11-13 with an early version of these rules, **before the guards** in rules 4 and 5
were added. Measure again once the chunk builder exists.

| Step | Chunks |
|---|---|
| Blocks at the start (234 documents) | 3,281 |
| After the colon rule | 3,115 |
| After the note and quote rule | 3,051 |
| After the small rule | 2,978 |

The guards change only a couple of chunks (two quotes in a row). The median chunk is about 32 words.
