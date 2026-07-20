<!--
SPDX-FileCopyrightText: 2026 Alexandre Gomes Gaigalas <alganet@gmail.com>

SPDX-License-Identifier: ISC
-->

# apycite

**Keep the quote next to the code it justifies, and prove it is still in the source.**

```rust
// cite(RFC 9112 § 3.2): "A client MUST send a Host header field (Section 7.2 of [HTTP]) in all HTTP/1.1 request messages."
if host_count == 0 {
    return violation(...);
}
```

`apycite` scans your tree for those comments, resolves each source, and writes an
[apysource](https://github.com/alganet/apysource) citations file. `apysource` then
fetches the real document and checks that the sentence is still in it.

When the spec moves under you, you find out — and you find out *where*:

```
  [FAIL] Fragments: snippet verified............. 2/3
         RFC 9112 (https://www.rfc-editor.org/rfc/rfc9112.txt) (1)
           client_host_header: snippet not found in extracted content
             closest match (94% similar, § 3.2)
               source says: A client MUST send a Host header field ... in all HTTP/1.1 request messages.
               not in that passage: response
             cited by src/rules/client_host_header.rs:29
```

Nothing checks that your *implementation* matches the sentence — no tool can, and
that judgement is reasoning work for humans at review time. Putting the quote next
to the branch is what makes the reasoning cheap. apycite's job is the outward half:
**the quote is real, verbatim, and still in the spec.**

## Install

```bash
pip install apycite       # brings apysource with it
```

## The grammar

```
<comment> cite(<source>[ § <section>][, <key>: <value>]…): "<quote>"
```

It is a comment, so it fits everywhere a comment fits — above a branch, inside a
`const` table, next to a match arm, in `#[cfg]`-gated code. That is the whole
reason it is a comment and not a macro.

**`<source>`** names an entry in your sources file. It is *not* a URL. apycite has
no idea what an RFC is, what HTML is, or where rfc-editor lives. That sentence was
a lie until the pattern that minted rfc-editor links moved out of this package; it
is not one now.

**`<key>: <value>`** takes **any apysource targeting key** — the list is read from
apysource at import, not copied. A targetter apysource ships tomorrow works in a
cite tomorrow, with no release of this package.

**`label: <name>`** is apycite's own key, not a targeting one. It names the fragment
in the generated store, so a cite can name itself for the sentence it enforces instead
of inheriting the path of whichever file happens to sort first. A labelled cite is left
out of the `(2)`, `(3)` numbering, and the same sentence cited in several places can be
named from any one of them.

**`§ <section>`** is sugar for `, section: "§ …"`, because a codebase citing RFCs
writes hundreds of them. One sugar; the general form is right there.

**The quote is required.** A citation that quotes nothing makes no claim anybody
can check.

### The quote may run onto the next lines

Normative sentences are long, and a line limit should not have to win against one:

```rust
// cite(RFC 9110 § 7.2): "A user agent MUST generate a Host header field in a
// request unless it sends that information as an ":authority" pseudo-header field."
if host_count == 0 {
```

```c
/* cite(RFC 9112 § 3.2): "A client MUST send a Host header field
 * (Section 7.2 of [HTTP]) in all HTTP/1.1
 * request messages." */
```

No continuation marker, no trailing backslash. **The quote ends on the line that
ends with a `"`** — which is the rule one line already obeys, where it reads as
"nothing may follow the closing quote". Lines are joined with a single space, and
apysource normalises whitespace on both sides of the comparison, so how you wrap a
quote is not a fact about it.

Two rules follow, and both stop the run rather than guess:

- **A cite may not be swallowed by the quote above it.** If a quote is left open,
  the line below it is not read forward into it — because that line might be
  another cite, and it would then be *gone*, from a run that exits 0.
- **Quotation marks pair up.** RFC 9110 writes `"Host"` and `":authority"`, never
  half of either, so a closed quote has an even number of `"`. Without that count,
  breaking a line right after an embedded mark would end the quote early — and the
  truncated quote is a *prefix of the real sentence*, so it is genuinely in the
  source and **verifies green** while the rest of it goes unchecked. That is the
  worst thing this tool could do, so it counts.

  The price: a quote containing a lone `"` — prose about the character itself —
  cannot be cited. Which mark closes `"the " character"` was never something to
  guess between; it is now refused instead.

What is *not* supported is elision. The quote is contiguous source text, and a
trailing `...` is the only way to say "and it goes on" (apysource prefix-matches).

## It is not a spec tool

Every apysource source class is reachable from a comment, in any language:

```rust
// cite(RFC 9110 § 7.2): "A user agent MUST generate a Host header field…"
```
```python
# cite(Fetch § 3.2): "The `Origin` request header indicates where a fetch originates from."
```
```lua
-- cite(UN Charter, section: Article 51): "Nothing in the present Charter shall impair…"
```
```javascript
// cite(MDN Origin, section: Origin header): "The HTTP Origin request header indicates…"
```
```css
/* cite(CSS Color 4, selector: #resolving-color-values): "…" */
```
```tex
% cite(Some Book, page_start: 40, page_end: 42): "…"
```

All four of the first ones are in the test suite, checked against the live
documents. A tool that only ever ran RFCs would be a lint script wearing a
general-purpose hat.

## The sources file

An ordinary apysource sources file — the same one `apysource check` reads. A cite
names an entry by its `label`:

```yaml
sources:
  - label: RFC 9110
    url: https://www.rfc-editor.org/rfc/rfc9110.txt
    type: text/plain
  - label: Fetch
    url: https://fetch.spec.whatwg.org/
    type: text/html
  - label: MDN Origin                 # MdnRepo claims this URL automatically
    url: https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Origin
```

Repo claiming, format detection, section trees, anchor inference, redirect
surfacing, and turning `RFC 9110` into a URL — none of that is apycite's. It is all
apysource's, and you reach it by writing a source entry.

Hand-written fragments in that file **survive into the output**, so the things the
grammar deliberately cannot say (a selector-only fragment, a `part_of` chapter
tree) cost you nothing.

`RFC NNNN` resolves without an entry — not because apycite knows what an RFC is,
but because **apysource ships the pattern**, next to the fetcher that has to know
the URL anyway. Another family is a `patterns:` block in the same sources file,
and it is apysource's key, not apycite's:

```yaml
patterns:
  - match: '^W3C (?P<slug>[a-z0-9-]+)$'
    source: {url: "https://www.w3.org/TR/{slug}/", type: text/html}
```

An entry beats a pattern, so pinning `RFC 9110` to datatracker is one entry.

What apycite *writes* is the expanded source — full URL, full media type — even
when the entry that produced it was a bare `- label: RFC 9110`. The generated file
is evidence, and evidence you have to hold a pattern table beside you to read is
not evidence. A reviewer sees the URL that was fetched.

## Commands

```bash
apycite extract                   # scan the tree, write the citations file
apycite extract --frozen          # ...or fail if the committed one is out of date
apycite extract --format turtle   # ...as RDF instead of YAML
apycite verify                    # check every quote against the source that says it
apycite ratchet                   # enforce the migration baseline
apycite styles --path x.zig       # which comment style a file gets, and why
```

There is no `apycite check`. That word is `apysource check`'s, and a CI log must
never leave a reader wondering which of two tools passed.

A sensible CI split — `extract --frozen` and `ratchet` are offline and fast enough
for every pull request; `verify` fetches, so it runs nightly:

```yaml
- run: apycite extract --frozen        # the committed file is current
- run: apycite ratchet                 # no new rule without a citation
- run: apysource check specs.yaml      # (or: apycite verify, nightly)
```

## Publishing the citations as RDF

The citations file *is* a graph — apycite has always parsed its own output into
one before writing it, as a guard. `--format turtle` keeps that graph instead of
throwing it away:

```toml
[apycite]
output        = "citations.ttl"
output_format = "turtle"
sources       = "sources.yaml"
```

What comes out is the map from your code to the sentences it implements: an
`sv:CiteSite` carrying the file and line, `prov:wasDerivedFrom` the fragment,
`oa:hasSource` the document. Someone else can then ask which projects depend on
RFC 9110 § 7.2 and get an answer.

For that to be true across projects, the identifiers have to be yours. Set a
`base:` in the **sources** file — it is apysource's key, in apysource's file, and
apycite carries it into what it writes:

```yaml
base: https://example.org/citations
sources:
  - label: RFC 9110
```

Without one, identifiers fall back to `urn:apysource:fragment_<label>`, which is
derived from the label and so identical to what every other project citing that
sentence would mint. Fine while the file stays with you; a silent merge of two
different citations the moment it does not.

Turtle is the only RDF form `--frozen` can compare, and that is why it is the
only one offered: the rest label their blank nodes afresh on every run, so a
committed file would show a diff on every commit and everyone would learn to
ignore the check.

## Nothing goes unlooked-at

A scanner meets a file whose language it does not know. The obvious thing is to
skip it — and that is a **silently dropped citation**: a cite in a `.zig` file goes
unread, the report says nothing, CI stays green, and the tool has verified nothing
and called it a pass.

So apycite does not skip. It rests on a theorem:

> **Every string that parses as a cite, in every comment style, contains the
> literal substring `cite(`.**

That is true by construction of the grammar, it is asserted over every style and
placement in the test suite, and it licenses the only safe skip in the tool: a
file with no `cite(` anywhere in it provably has no cites, whatever language it is
written in. Every other file must be *read*:

| what we found | what happens |
|---|---|
| a cite | ✅ extracted |
| a `cite` that does not parse | ❌ error — a typo must break CI, never drop a quote |
| cite-shaped text that is not a citation (a string literal, prose) | ❌ error (configurable to `warn`) |
| **cite-shaped text in a file with no comment style** | ❌ **error — apycite will not call a tree clean that it could not read** |
| a file with no comment style and no `cite(` | ✅ safe skip, *by the theorem* |
| a file that will not decode | ❌ error — we could not read it, so we will not promise it holds no cites |
| a binary file | skipped, **and counted in the report** |
| an excluded path | skipped, **and the glob is printed every run** |

`sum(buckets) == paths walked` is a test. And extracting **zero** cites is not a
pass — a validator that validated nothing has not passed. Pass `--allow-empty` if
a tree with no cites is genuinely what you meant.

*Paths*, not files, because of one case: a glob that excludes everything under a
directory (`**/.git/**`, `vendor/*`) is answered by not entering it, and the
directory is what gets counted. Walking a `.git` with a hundred thousand loose
objects only to discard them one at a time was the largest cost in a scan of a
real repository — and having not looked inside, apycite will not claim a count
for what is there.

A file whose text does not contain the four characters `cite` is read, counted as
scanned, and not parsed further. That is licensed by a slightly stronger claim
than the marker theorem: every citation contains `cite(`, and every *complaint*
about a citation — including `// cite this properly please`, which announces
itself and then fails to parse — contains at least `cite`. Skipping on the
narrower `cite(` would have silenced that error, which is the failure this whole
section exists to forbid.

## The ratchet

Adopting cites across a codebase with hundreds of rules is a campaign, not a
branch. The baseline is a committed list of in-scope files that still carry no
cite, and **it may only ever shrink**:

```bash
apycite ratchet --init     # once: list every file still to migrate
apycite ratchet            # CI: fail if a file enters the list, or left it silently
apycite ratchet --write    # after a batch: shrink the list
```

`--write` **will not add a file**. A new rule with no citation is precisely what
the baseline exists to catch, and adding it automatically would be the tool
helping you not notice. Putting a file *into* the baseline takes a human edit,
where a reviewer will see it.

When the baseline empties, the permanent rule — *every file in scope carries at
least one cite* — is already being enforced, with no new code.

## License

ISC.
