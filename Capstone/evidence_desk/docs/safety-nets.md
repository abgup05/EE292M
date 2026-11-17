# Safety nets

*Written 17 November 2026 for the Week 8A hands-on. Each fact about the laptop was read by the command shown, in the Claude Code session that did the catch-up. Lines marked "to confirm" are things only I can check.*

## 1. Copies: where are they, and which is offline?

The rule from the lecture is 3-2-1: three copies, two kinds of storage, one offline, and a restore that has been tested.

| What | Copy 1 | Copy 2 | Copy 3 | Offline copy |
| --- | --- | --- | --- | --- |
| Code, fixtures, cassette, golden records (git) | This laptop | GitHub, private repository | none | **none** |
| The record: runs, decisions, saved theses (`data/record/record.sqlite`) | This laptop | `backups/` on the same disk, written by `make backup` | none | **none** |
| Keys (`.env`) | This laptop | can be reissued by the provider | — | — |

- `tmutil destinationinfo` answers "No destinations configured": this laptop has no Time Machine backup.
- So the code has two copies and the record has, in effect, one: a backup on the same disk survives a bad migration or a deleted file, not a failed disk or a lost laptop.
- The restore is tested (`make restore-check` restores the newest backup and compares every run, decision and thesis with the live record, each as the text that is stored, and fails on a record this version cannot read), but only from that same disk. Until review 6 it compared runs by id only and skipped records that no longer parsed on both sides, so it could pass on a record the app could not show.
- The record and `backups/` are both ignored files inside the working tree, so `git clean -fdx` or deleting the checkout removes the original and every backup together. `make backup-status`, printed by `make up`, says how old the newest backup is and what it lacks.
- The app and a one-off container may write the record at the same time (WAL mode, across Docker Desktop's file sharing). `make two-writers` ran that on a scratch record: 2,000 writes from each side at once, integrity and every row checked (`docs/evidence/two-writers.txt`). One run, on this laptop; it says nothing about a power cut.
- **To do, mine:** copy `backups/` to somewhere that is not this laptop (an encrypted external disk, or an encrypted archive in cloud storage), and run `make restore-check` against that copy once.

## 2. Keys: what reaches what, and which have no passphrase?

| Key | Where it is kept | What it can reach | Notes |
| --- | --- | --- | --- |
| Anthropic API key | `.env`, gitignored, plain text | `api.anthropic.com`, billed to my account | Two keys are in the file; both were refused for lack of credit on 17 November. **One was pasted into an agent conversation in plain text and should be rotated** |
| GitHub token | macOS keychain, through `gh` (`gh auth status`) | Every repository of mine, public and private, read and write; scopes `repo`, `workflow`, `gist`, `read:org` | Wider than this project needs. Git runs over HTTPS with this token |
| SSH keys | `~/.ssh` holds no public key (`ls ~/.ssh/*.pub`) | — | Nothing to passphrase; to confirm that no key lives elsewhere |
| SEC EDGAR | none | public data | The User-Agent is a generic client name; no contact address is sent unless `SEC_USER_AGENT` is set |

**What the agent session could reach.** The lecture's advice is to write this down before handing over a key. I did not; this is after the fact. The unattended session ran as my user: it could read my home directory, write anywhere it was not blocked, push to GitHub with the token above, start Docker containers, call the Anthropic API with the key in `.env`, and reach the internet. What limited it was its instructions and the rules in `AGENTS.md`, which is advice, not enforcement. It pushed only to the feature branch and never to `main`. The repository now has a `.claude/settings.json` with a short deny list: the file-reading tool on `.env`, force-pushes, and a push to `main`. **That is partial enforcement, not a boundary.** The rules match command prefixes, so a reordered command gets past them; a shell command can still read `.env`; and nothing stops a direct `docker`, `curl` or `gh` call, which `AGENTS.md` forbids only in words. Denying those outright would also stop my own sessions, so I have left that decision to make. A real boundary is a sandbox, or a key that is not in the working tree at all.

## 3. Ports: what listens?

`lsof -nP -iTCP -sTCP:LISTEN` on 17 November:

| Listener | Address | Whose |
| --- | --- | --- |
| The Evidence Desk app | `127.0.0.1:8766`, only while `make up` runs | This project. Local only, as the compose file says |
| A Docker container | `*:8088`, all interfaces | **Not this project.** To confirm what it is; it should be bound to `127.0.0.1` or stopped |
| Control Center (AirPlay receiver) | `*:5000`, `*:7000`, all interfaces | macOS. Can be turned off in Settings if unused |
| Node development servers | `127.0.0.1:3000`, `127.0.0.1:3002` | Local only |
| PostgreSQL | `127.0.0.1:5432`, `[::1]:5432` | Local only |
| Logi Options, `rapportd` | all interfaces, high ports | Vendor and macOS services |

Nothing of this project answers on the network. Two things on this laptop do (`*:8088`, AirPlay), and I had not known about either.

## 4. What catches a wrong result, and what slips past

The layers, in the order a result meets them. The point of stacking them is that their holes should not line up.

| Layer | What it catches | Its hole |
| --- | --- | --- |
| Request validation at the API | Malformed input, unknown tickers, private-network URLs | A well-formed claim that is vague or untestable |
| The quote check | A quote that is not word for word in the filing | A real quote that does not mean what the finding says |
| The number check | A number in a finding that is in neither its quotes nor its cited figures | A right number attached to the wrong thing; numbers written as words |
| The period check (reported only) | A year or fiscal label in a finding's statement that is nowhere in its quotes, its cited figures or the period of a filing it quotes. It is shown on the finding and counted; nothing is withheld | A year that is in the evidence for another reason: the wrong column of a table, where the quote shows both years. With a wrong year planted, 21 of 25 one year back and 25 of 25 three back were flagged. No real period error has been seen |
| The meaning check | A verified finding whose excerpts a second model judges do not support the statement or stance; it is withheld with the reason | A misreading the checker shares (same model family; same model is flagged as a coverage limit). Measured on planted mismatches, real quotes moved under a statement they do not belong to: it rejected 150 of 152, the easy kind; a quote on the right topic that does not carry the statement has not been tried. A check that could not run leaves findings "not checked" and makes the run partial |
| The verdict rule | A model asserting a verdict without verified evidence | A wrong stance on a verified finding that the meaning check passed |
| The answer key for figures | A wrong formula, period or restatement, on three companies | A company whose XBRL tags differ from those three |
| The tripwire | Any change upstream of a recorded run, and since version 8 any change to the comparison of two recorded filings | A change that is wrong and was re-baselined without reading the diff |
| The replay test | A prompt edited without re-recording | Whatever the recorded answers got wrong, replayed faithfully |
| The page test | A wrong label, glyph, count or missing badge; a figure drawn under the wrong period; a page rendered before its last change | Layout, contrast, whether a person understands it |
| The tagged total | A breakdown whose members do not add up to the filing's own tagged total: a member missed, counted twice, or read at the wrong scale | A number under the wrong label that still adds up; a filing that tags no total |
| A blind review by another model | Claims the repository does not support | Blind spots the reviewer shares with the builder: both are Claude models |
| The reader's accept or reject | A finding that misreads its quote | A reader who accepts without opening the passage |

**What slips past all of them today:**

- **A wrong stance on the right topic.** Every mechanical layer passes a real sentence that the engine misread. The meaning check asks a second model, and it does reject quotes that are about something else (150 of 152 planted ones). But it is another Claude model reading the same excerpts, it rejected only 1 of 78 real findings, and nothing has measured what it does with a quote that is on the topic and does not carry the statement. The reader is still the last layer.
- **A passage that was never retrieved.** If the passage that matters is not in the eight shown to the engine, the claim reads "not addressed" or is judged on weaker evidence. On the golden set that is 15 of 24 cases with the claim's own words and 6 of 24 with the planner's queries. No layer after retrieval can see what retrieval left out. The list of changed paragraphs under each claim is a second, independent look at the newest filing, by keyword only.
- **Correlated reviewers.** The builder, the stand-in that answered the prompts and every reviewer are Claude models. Their mistakes are not independent. No person has yet read the golden cases or the code.
