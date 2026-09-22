# Becoming a GSoC 2027 Contributor — Action Plan, Org Shortlist & Draft Proposal

### For Abdelaziz Guelfane

## TL;DR

- You qualify for GSoC 2027 via the "student" route (enrolled PhD student), your prior industry jobs do not disqualify you, and the single best-fit organization is **DBpedia** — its live projects are exactly your thesis toolkit (entity resolution, entity linking, relation extraction over a knowledge graph) and heavily multilingual/transformer-based, and there is currently no active Arabic DBpedia chapter, giving you a rare, truthful differentiator with your native Arabic + AraBERT NER experience.
- The path is: pick DBpedia now (ML4SCI as backup), land 2–4 genuine small pull requests of your own before the March 2027 window, engage mentor Tommaso Soru (@tsoru) early on the DBpedia forum, and submit a self-written PDF proposal early. A Medium (~175h) project is the right size for a full-time PhD; consider Large (350h) only if your schedule and mentor agree.
- Three hard constraints to clear first, yourself: (1) confirm you are legally eligible to work in France for the program duration; (2) read your GE HealthCare contract for outside-work/stipend/IP clauses; (3) write everything in your own voice — GSoC's official guide says AI-written proposals "could result in an automatic rejection."

## ⚠️ How to use this document

This is a scaffold and research dossier, **not** a finished application. The official GSoC FAQ states: *"Always check an organization's specific AI policy before applying. Please be aware that using AI to write your GSoC proposal could result in an automatic rejection by the organization, depending on their individual guidance."* You **must** rewrite every proposal and every message to mentors in your own words, and never present any contribution, PR, or achievement that is not genuinely yours. Placeholders in `[brackets]` are facts only you can supply.

## One-Page Checklist — "What you must do, by when"

*GSoC 2027 dates were not published as of 22 Sep 2026; the dates below are estimates extrapolated from the confirmed 2026 calendar. Verify on [summerofcode.withgoogle.com](https://summerofcode.withgoogle.com) when announced.*

### NOW – November 2026 (foundation)

- [ ] Confirm eligibility: 18+, never accepted as a GSoC contributor before, "student or open-source beginner." You qualify on the student criterion.
- [ ] Work-eligibility check (France): GSoC rules require you to be eligible to work in your country of residence for the program's duration. Verify your own status — do not rely on this document.
- [ ] Contract check (critical): Read your GE HealthCare employment/research contract for outside-work/moonlighting, stipend-acceptance, and IP/assignment clauses. Get written clearance if needed.
- [ ] Pick 1 primary + 1 backup org from the shortlist (recommended: DBpedia + ML4SCI).
- [ ] Create/confirm a public GitHub profile; complete the README; pin relevant repos (e.g., `erc_backbone` if public).
- [ ] Join each org's community channels; read their CONTRIBUTING and AI policies.

### December 2026 – January 2027 (get known)

- [ ] Introduce yourself on the org forum/chat, in your own words.
- [ ] Land your first small merged PR (docs/tests/small bug) — YOUR OWN WORK.
- [ ] Study the previous year's ideas list and past accepted proposals.

### February 2027 (orgs announced ~mid/late Feb)

- [ ] When the accepted-orgs list drops, confirm your target org is in.
- [ ] Comment on the specific idea thread; ask one sharp technical question.
- [ ] Land 2–3 more PRs of increasing substance.

### March 2027 (application window, ~mid–end March)

- [ ] Draft the proposal early; share as a draft for mentor feedback.
- [ ] Incorporate feedback; keep contributing.
- [ ] Prepare a PDF of your proposal (required).
- [ ] Submit on the GSoC website before the deadline (18:00 UTC). No extensions, ever. Max 3 proposals; only 1 can be accepted.

### April 2027

- [ ] Respond quickly to mentor questions. Accepted contributors announced ~late April/early May.

### May–September 2027 (if accepted)

- [ ] Community bonding (~May), coding (~late May–Aug), midterm & final evaluations. Flag PhD conference/exam weeks to your mentor in advance.

## Key Findings

1. **You are eligible via the student route.** GSoC's mandatory rules are: 18+, eligible to work where you reside, "student or open-source beginner," accepted no more than once before, and not in an embargoed country. As an enrolled PhD student you satisfy the student limb outright.
2. **Your industry background is not a barrier**, but frame yourself as new to open-source contribution, not new to software. The FAQ cautions that professionals often struggle with the time commitment — a warning, not a disqualification.
3. **DBpedia is the strongest, confirmed match** for your knowledge-graph + multilingual-NLP + transformers profile, and it welcomes original (self-proposed) ideas — opening the door to an Arabic chapter proposal.
4. **A Medium (~175h) project fits a full-time PhD.** PyMC — otherwise a great Bayesian fit — defaults to 350h and requires you to pre-negotiate any 175h arrangement, which lowers its practical rank.
5. **AI policy is now a rejection risk.** GSoC-wide guidance plus varied, sometimes strict org policies mean you must author everything yourself and disclose any research-only AI use.
6. **Timing matters more than brilliance.** Prior mentor interaction is described officially as "the most critical factor," so the pre-application contribution period (now → March 2027) is where the application is really won.

## Details

### PART 1 — Requirements, eligibility, and timeline

#### 1.1 Eligibility

*(official — developers.google.com/open-source/gsoc/faq and summerofcode.withgoogle.com)*

Mandatory: 18+ at registration; eligible to work in your country of residence for the program's duration; "student or open-source beginner"; accepted as a GSoC contributor no more than once previously; not residing in a U.S.-embargoed country (France is fine).

The "beginner" limb is defined generously — per GSoC admin guidance on the official google-summer-of-code-discuss group:

> "You would still be considered a beginner if your experience only includes: Personal or class projects... Open source projects that are only used at a single institution... Opening a small number (<10) of issues or pull requests against various open source packages... If you are otherwise a regular contributor to an open source project, you're not a beginner."

You qualify via the student route regardless of your industry history.

**Does a PhD student with prior industry jobs qualify? Yes.** The FAQ notes GSoC targets newcomers and that "professionals often find the required time commitment difficult to balance" — a caution, not a bar. Your Carrefour/SLB/Taager/GE HealthCare roles do not disqualify you; present yourself honestly as new to open-source contribution.

**Work-eligibility (France).** The rule requires you to be legally eligible to work where you reside for the program's duration. The official proposal guide warns that people on student or other visas "could have restrictions on the number of hours" or "may not be eligible to participate at all." Verify your own situation. This document does not assess your immigration/visa status.

**GE HealthCare contract.** Because your PhD is in collaboration with GE HealthCare (not a CIFRE contract) and you hold a current role there since Dec 2025, check your contract for (a) outside-work/moonlighting permission, (b) whether accepting a Google stipend conflicts with employment terms, and (c) IP-assignment clauses that could claim ownership of open-source code you write. Resolve these before applying. (Note: DBpedia's rules add that "DBpedia does not accept any contributor that is affiliated with a DBpedia member organization" and require disclosure of any relations between contributors and mentors/member organizations — not an issue for GE HealthCare, but disclose truthfully.)

#### 1.2 Application mechanics (official)

Max 3 proposals; only one can be accepted. Proposal must be uploaded as a PDF. No deadline extensions — "There are absolutely no extensions to deadlines in GSoC proposal submissions for anyone, ever." Submit early, labelled as a draft, to solicit mentor feedback; you can edit until the deadline. Prior mentor interaction is "the most critical factor."

#### 1.3 Project size & stipend (France)

Per the official FAQ, "Projects are scoped for ~90 hours (Small), ~175 hours (Medium), or ~350 hours (Large)," over "a flexible timeframe of 8–22 weeks." Given your full-time PhD, Medium (~175h) is the right default. Consider Large (350h) only if your PhD schedule genuinely allows ~2× sustained effort, the mentor agrees the scope fits, and you use the mentor-agreed extension option (up to 22 weeks).

Per Google's official 2026 stipend page:

| Size | Base amount (USD) | PPP-adjusted range (USD) |
|---|---|---|
| Small (~90h) | $1,500 | $750 – $1,650 |
| Medium (~175h) | $3,000 | $1,500 – $3,300 |
| Large (~350h) | $6,000 | $3,000 – $6,600 |

As a higher-cost country, France's PPP multiplier sits near the top of each band, so a Medium project in France is likely near the ~$3,000–$3,300 maximum and a Large near ~$6,000–$6,600 — an estimate; confirm on Google's country-specific chart for 2027.

Payment is in two installments: per the official page, "First Evaluation (paid July 11): 45%" and "Final Evaluation (paid September 1): 55%." You are paid for passing evaluations, not for whether code is merged.

#### 1.4 Timeline — GSoC 2026 confirmed

*(per Google Open Source Blog and the official timeline)*

| Milestone | Date |
|---|---|
| Org applications | Jan 19 – Feb 3, 2026 |
| Accepted mentoring orgs (185 communities) published | February 19, 2026 (18:00 UTC) |
| Contributor discussion period | Feb 19 – Mar 15 |
| Contributor application window | March 16 – 31, 2026 (18:00 UTC) |
| Accepted contributors announced | April 30, 2026 (18:00 UTC) |
| Community bonding | through May 25 |
| Coding period | May 26 – August 23, 2026 |
| Midterm evaluation | mid-July |
| Final evaluations | Aug 24 – Sep 1 |
| Extended projects | can run to ~November 2026 |

**GSoC 2027 (estimated, same rhythm):** orgs announced ~mid-to-late February 2027; contributor applications ~mid-to-late March 2027; acceptances ~late April/early May 2027; coding ~late May–August 2027. Estimated until Google publishes 2027 dates.

#### 1.5 AI policy

GSoC-wide, the FAQ warns AI-written proposals can be an automatic rejection; Google's "Guidance for GSoC Contributors using AI tooling in GSoC 2026" stresses the contributor "retains 100% responsibility," must fully understand and verify any AI output, and should use AI "mostly for research and less for code generation," with each org setting its own policy. Observed org stances vary widely:

- **NumFOCUS** (PyMC's umbrella): AI use "generally acceptable but determined by each sub-organization/project"; contributors "must clearly cite any AI tools used."
- **DBpedia**: No published DBpedia-specific AI policy was found in their forum, GitHub, or application doc — treat AI use as governed only by general quality/authorship norms and ask on the forum first *(unconfirmed)*.
- **Strict examples**: Typelevel — "do not use AI to write your GSoC proposal"; LibreHealth — "The use of AI is forbidden at any point during the program"; Jenkins — "You may not copy-paste AI-generated code directly into a Pull Request."

**Bottom line:** write everything yourself; if you use AI for grammar/research only, disclose it and be ready to explain every line.

### PART 2 — Organization shortlist (ranked by fit)

Your differentiators: probabilistic entity resolution + knowledge graphs (thesis); trilingual Arabic (MSA + Moroccan Darija) / French / English with hands-on AraBERT Arabic NER (Taager); transformers + post-training quantization of multilingual encoders; Bayesian inference; POMDP/RL control; data pipelines/MLOps; and medical-imaging ML (MRI/CT via GE HealthCare).

#### #1 — DBpedia (BEST FIT) — knowledge graphs + multilingual NLP + transformers

**Why it fits you:** DBpedia's core work is your thesis toolkit — entity resolution, entity linking, relation extraction over a knowledge graph — and its 2026 projects are heavily multilingual and transformer/LLM-based. Your native Arabic + AraBERT NER + multilingual-encoder research is a rare, genuine edge: there is currently no active Arabic DBpedia chapter (the old one has been offline since ~2017), so you can extend the existing multilingual pipeline or propose an Arabic chapter as an original idea.

**2026 ideas that match:** "Towards a Neural Extraction Framework" (running since 2021, Python; predicate resolution + neural relation mining validated against the DBpedia ontology; mentor Tommaso Soru/@tsoru, co-mentor Ara Yeroyan); "Modernizing & Multilingualizing DBpedia NLP Pipeline"; the Amharic, Hindi, and Yoruba language-chapter projects (LLM-based IE — direct templates for an Arabic analogue); "Agentic Question Answering over DBpedia"; "NLP datasets for the Databus."

**Stack:** Python + Jupyter (Neural Extraction Framework); Scala/Java (core extraction-framework); SPARQL, RDF.

**Community channels:** Forum [forum.dbpedia.org](https://forum.dbpedia.org) (GSoC category is the required channel — "All GSoC related questions ... should go through this channel"); email dbpedia@infai.org; DBpedia Slack; mailing lists `dbpedia-discussion` and `dbpedia-gsoc`; GitHub [github.com/dbpedia](https://github.com/dbpedia).

**Mentor responsiveness:** High. Tommaso Soru (@tsoru, mommi84@gmail.com) explicitly invites applicants to share a proposal Google Doc for feedback before the deadline; Dr. Sanju Tiwari mentors the Hindi chapter; Amharic mentors include Hizkiel Alemayehu, Tilahun Tafa, and Ricardo Usbeck. In GSoC 2025 DBpedia selected five proposals and four passed final evaluation.

**Original proposals:** Allowed and encouraged — "Please make sure to get in touch with our mentors (preferably via GitHub) before finalizing your proposal." No merged PR is mandated, but a prior contribution + early mentor contact is strongly expected.

**Concrete beginner issues you could do YOURSELF** (verified open in `dbpedia/extraction-framework`, Scala/Java):

- [#825 "Refactor GenderExtractor to use context.ontology instead of hardcoded URIs"](https://github.com/dbpedia/extraction-framework/issues/825)
- [#819 "Better default User-Agent for the Extraction Framework"](https://github.com/dbpedia/extraction-framework/issues/819)
- [#760 "Duration parser in DIEF fails for words written in non latin alphabets"](https://github.com/dbpedia/extraction-framework/issues/760) (directly relevant to Arabic script)
- [#755 "Typo: J.K._Rowling instead of J._K._Rowling"](https://github.com/dbpedia/extraction-framework/issues/755)

The Python Neural Extraction Framework has no formally labelled "good first issues"; the community advises starting with reproducibility/docs/refactor fixes and opening an issue first for sign-off.

#### #2 — ML4SCI (Machine Learning for Science) — medical-imaging ML + transformers

**Why it fits you:** ML4SCI ran a medical-imaging track in 2026 (the PREDICT projects on Coronary Artery Calcium (CAC) segmentation, radiomics, and physics-informed plaque simulation) — a direct overlap with your GE HealthCare MRI/CT work — plus many transformer/foundation-model projects. Projects are 175h (Medium).

**2026 ideas that match:** "Building and Comparing Segmentation Strategies for Coronary Artery Calcium (CAC)"; "Radiomics Feature Extraction and Calcium Phenotype Discovery"; "Data Augmentation Using Physics-Informed Plaque Growth Simulation"; "Event Classification With Masked Transformer Autoencoders."

**Stack:** Python, PyTorch, transformers, scientific ML.

**Community channels:** ml4-sci@cern.ch, Gitter, announcements mailing list (needs a CERN lightweight account); per-project GitHub repos (e.g., `ML4SCI/DeepLense`). Applicants typically complete a per-project evaluation test.

**Original proposals:** generally apply to a listed project with a mentor; contact admins to propose a new project.

**Beginner entry:** open an onboarding issue on the relevant repo (as GSoC 2026 applicants did on `ML4SCI/DeepLense` #82) and complete the project's evaluation task.

#### #3 — NumFOCUS / PyMC — Bayesian inference (your thesis core)

**Why it fits you:** your Bayesian material-flow analysis and probabilistic modeling map straight onto PyMC's mission.

**Caveat (important):** PyMC states GSoC 2026 projects are 350h by default — "We will not accept 175h applications from people with whom we haven't discussed their time commitments before submitting." For a Medium project you must negotiate on their Discourse first; given your PhD load this friction lowers PyMC's practical rank.

**Ideas that match:** "Scalable Online Bayesian State Space Models," "Bayesian Survival Models," spatial GP methods (Nearest-Neighbor GPs, CAR/ICAR/BYM).

**Stack:** Python, PyTensor, NumPy/SciPy, JAX/Numba.

**Community & requirement:** PyMC Discourse ([discourse.pymc.io](https://discourse.pymc.io)); you must make a PR to PyMC/PyTensor (even a doc/bug fix) to be considered.

**Sibling option — pgmpy** (probabilistic graphical models): "we strictly require at least one contribution/PR to the package for your application to be considered" — relevant to your causal/Bayesian interests.

#### #4 — Farama Foundation — reinforcement learning / POMDP (Python)

**Why it fits you:** your POMDP decision layers and RL/POMDP interests match Farama's Gymnasium (single-agent RL API), PettingZoo (multi-agent), and Minari (offline RL datasets) — all Python.

**Stack:** Python, NumPy, JAX/PyTorch, MuJoCo.

**Community channels:** Discord (linked from the Gymnasium GitHub), CONTRIBUTING.md, GitHub issues.

**Beginner entry:** Gymnasium and siblings maintain good-first-issue-style tickets and welcome doc/wrapper/test PRs.

**Alternative (Julia) — JuliaPOMDP / POMDPs.jl:** the most direct POMDP match, but Julia, not your primary stack — pursue only if you want to invest in Julia. The broader Julia (JuliaLang) GSoC org runs many RL/Bayesian projects.

#### #5 — Apache Software Foundation — data transformation / data pipelines

**Why it fits you:** your data-engineering/MLOps background (Carrefour demand forecasting, SLB MLOps) maps to Apache Beam (unified batch/stream pipelines; Java/Python/Go) and Apache Arrow (columnar data; multi-language). ASF is large and beginner-friendly with structured mentorship.

**Stack:** Java, Python, Go, Scala, C++ (varies by project).

**Community channels:** project mailing lists; JIRA filtered by the year's label (2026 used "gsoc2026": [issues.apache.org/jira/issues/?jql=labels+=+gsoc2026](https://issues.apache.org/jira/issues/?jql=labels+=+gsoc2026)); [community.apache.org/gsoc](https://community.apache.org/gsoc).

**Process note:** proposals must have an identified mentor by ~early April or they are down-rated; unscored proposals are rejected.

**Original proposals:** allowed — propose work not on the list via a project's dev mailing list.

#### #6 — DeepChem (optional) — scientific ML + transformers

**Why it fits you:** transformer foundation models for chemistry/biology (ChemBERTa, MolFormer), HuggingFace integration, PyTorch. Medium projects exist (e.g., symbolic regression).

**Community channels:** GitHub Discussions (`deepchem/deepchem` #4703 lists 2026 ideas), [forum.deepchem.io](https://forum.deepchem.io). Applicants are expected to make small PRs (e.g., around the HuggingFace integration) before proposing.

---

**Orgs that explicitly allow original (non-ideas-list) proposals:** DBpedia, Apache Software Foundation, and (via mentor contact) ML4SCI and DeepChem. PyMC is open to other topics if discussed first on Discourse.

**A note on "name-brand" NLP orgs:** Hugging Face and spaCy/Explosion are frequently predicted but were not confirmed GSoC 2026 mentoring orgs in the sources reviewed; do not assume they will appear in 2027. If NLP is your priority, DBpedia is the confirmed, well-matched route.

### PART 3 — Month-by-month action plan (Sept 2026 → March 2027 deadline)

**Pre-proposal contributions must be entirely your own work.** Never submit AI-generated code or PR descriptions to build your track record — several orgs treat this as disqualifying.

- **September 2026:** Finalize eligibility + contract clearance. Choose DBpedia (primary) + ML4SCI (backup). Set up your public GitHub. Read DBpedia's forum, GSoC page, and CONTRIBUTING; skim the Neural Extraction Framework repo and run last year's pipeline locally.
- **October 2026:** Register on the DBpedia forum; post a genuine introduction (your KG/entity-resolution/multilingual background, in your own words). Pick one verified starter issue (e.g., #760 non-Latin duration parser — plays to your Arabic-script knowledge; or #825 refactor). Comment, get sign-off, open your first PR.
- **November 2026:** Land 1–2 more small PRs. Start a Python contribution to the Neural Extraction Framework (reproducibility or docs fix), opening an issue first. Study 2026 ideas threads (NEF, Amharic/Hindi chapters).
- **December 2026:** Draft a rough concept — an Arabic/multilingual extension of the Neural Extraction Framework (leveraging AraBERT + multilingual encoders) — and float it informally with @tsoru on GitHub/forum to confirm mentor interest. Keep contributing.
- **January 2027:** Convert the concept into a structured proposal outline mapped to the GSoC timeline. Get informal feedback. Continue small PRs to stay visible.
- **February 2027:** When the accepted-orgs list is published (~mid/late Feb), confirm DBpedia is in. Post a specific technical question on the idea thread. Finalize which idea you're targeting.
- **Early–mid March 2027:** Write the full proposal in your own voice. Share it early (Google Doc / GSoC draft) for mentor comments. Iterate.
- **By the March deadline:** Export to PDF; submit on the GSoC website well before 18:00 UTC on the deadline day. Submit at most 2–3 high-quality proposals. No extensions.
- **April–May 2027:** Answer mentor questions fast; if accepted, begin community bonding.

### PART 4 — Full draft proposal (for #1: DBpedia)

> **SCAFFOLD — REWRITE IN YOUR OWN VOICE.** DBpedia has no published AI policy; some orgs reject AI-written proposals outright. Use this only as a structural skeleton. Replace all `[placeholders]`. Confirm the mentor and exact idea scope on the forum before submitting.

**Title:** An Arabic Language Chapter for DBpedia: Transformer-Based Multilingual Information Extraction and Entity Linking in the Neural Extraction Framework

**Contributor & contact information**

- Preferred name: Abdelaziz Guelfane
- Email: `[email]`
- GitHub: `[GitHub URL — a profile at github.com/Abdelaziz03 appears to match you; confirm and use your real handle]`
- Website/portfolio: `[website]`
- LinkedIn: `[URL]`
- Location / timezone: Paris, France — Europe/Paris (UTC+1 winter / UTC+2 summer)
- University: Laboratoire Génie Industriel (LGI), CentraleSupélec, Université Paris-Saclay

**Synopsis.** DBpedia's multilingual coverage is strong for some languages but has no active Arabic chapter (the previous one has been offline since ~2017), despite Arabic being among the most-spoken languages worldwide. This project extends DBpedia's Neural Extraction Framework with an Arabic information-extraction and entity-linking pipeline: extracting subject–predicate–object triples from Arabic Wikipedia text, linking entities to the DBpedia ontology, and validating outputs against it. The pipeline builds on transformer encoders for Arabic (e.g., AraBERT-family models) and modern multilingual encoders, following the architecture already proven for the Hindi and Amharic chapters. Deliverables include a reproducible Arabic IE pipeline, an evaluation harness with a small gold-standard test set, and documentation enabling the community to maintain and extend it.

**Benefits to the community**

- Adds a new language chapter for a major world language, potentially generating a large volume of new triples for the public DBpedia knowledge graph.
- Reuses and hardens the existing Neural Extraction Framework rather than duplicating effort, contributing multilingual robustness (including non-Latin-script handling) that benefits other chapters.
- Provides an evaluation harness and gold-standard sample that raise extraction-quality standards across chapters.
- Demonstrates a repeatable recipe for spinning up additional low-resource-language chapters.

**Deliverables & work breakdown structure** (R = required, O = optional)

1. (R) Investigation & design — survey Hindi/Amharic pipelines; select Arabic transformer encoders; define ontology-mapping approach and evaluation metrics; write a short design note.
2. (R) Data ingestion — Arabic Wikipedia dump ingestion + text cleaning; handle Arabic script normalization and diacritics.
3. (R) Core IE pipeline — NER + relation extraction producing candidate triples using Arabic encoders.
4. (R) Entity & predicate linking — link surface forms to DBpedia URIs; resolve predicates against the ontology (leveraging your entity-resolution background).
5. (R) Validation layer — validate triples against the ontology; filter low-confidence outputs.
6. (R) Evaluation harness + gold set — build a small annotated Arabic test set; report precision/recall.
7. (R) Tests & CI — unit tests for each module; reproducible environment.
8. (R) Documentation — README, setup guide, tutorial notebook.
9. (O) Darija/dialectal exploration — pilot handling of Moroccan Darija surface forms.
10. (O) Quantization — apply post-training quantization to the encoders for faster/cheaper inference (ties to your PTQ research).
11. (O) SPARQL/demo endpoint — expose sample results.

**Milestones & schedule** (mapped to the estimated GSoC 2027 timeline)

- Community bonding (~May): finalize design note (D1); set up environment; agree metrics with mentor. *(Required)*
- Coding weeks 1–3: data ingestion + cleaning (D2). *(Required)*
- Weeks 4–6: core IE pipeline (D3); begin tests (D7). Midterm deliverable: working end-to-end extraction on a sample. *(Required)*
- Midterm evaluation (~mid-July).
- Weeks 7–9: entity & predicate linking (D4) + validation layer (D5). *(Required)*
- Weeks 10–11: evaluation harness + gold set (D6); documentation draft (D8). *(Required)*
- Week 12 ("pencils down"): finalize tests, documentation, final report. *(Required)*
- Stretch (if time / extended timeline): D9–D11. *(Optional)*
- Time buffer: `[insert your PhD exam/conference weeks]` reserved as reduced-capacity weeks.

**Related work & how this differs.** DBpedia already runs neural IE for English and, via GSoC, Hindi and Amharic chapters, and maintains a knowledge-graph-embeddings line of work. This project differs by targeting Arabic, absent from the current chapters, and by explicitly addressing non-Latin-script and dialectal challenges. It reuses the Neural Extraction Framework's architecture rather than reinventing it and adds an evaluation harness. It is distinct from generic multilingual pipelines because it is tuned to Arabic morphology and to the DBpedia ontology. `[Cite the specific Hindi/Amharic repos and any Arabic-DBpedia literature you build on.]`

**Availability & time commitment** (be upfront)

- Full-time PhD student (entering 2nd year in 2026–2027). Plan to commit ~`[X]` hours/week to a Medium (~175h) project, front-loading community bonding.
- Known reduced-capacity periods: `[exam weeks]`, `[conference/paper-deadline weeks — e.g., around ICML/NeurIPS-related submissions]`. Will flag any changes to the mentor as early as possible.
- Available on `[forum/GitHub/Slack]` during `[hours, Europe/Paris]`.
- Other commitments: my GE HealthCare role — I have confirmed my contract permits this participation. `[Confirm before submitting.]`

**Biographical information** (truthful — no invented achievements)

- Doctoral researcher at LGI, CentraleSupélec / Université Paris-Saclay (in collaboration with GE HealthCare). Thesis: AI-driven digital twins for circular service-parts supply chains in medical imaging (MRI, CT), combining probabilistic entity resolution, Bayesian material-flow analysis, and POMDP-based decision layers. Built the Python package `erc_backbone`.
- Ongoing research on post-training quantization of multilingual encoders (a NeurIPS 2026 NeurReps workshop submission framing PTQ as geometric distortion; related ICML-targeted work). *(Describe as submissions/ongoing, not accepted.)*
- Double engineering degree (Diplôme d'Ingénieur, AI specialization) — CentraleSupélec and École Centrale Casablanca; exchange semester at ESSEC. Background in mathematics, mechanics, fluid dynamics, finite-element methods; self-taught coder; lifelong hardware projects (SolidWorks; a monowheel with control board and sensors).
- Industry: Data Scientist at Carrefour (demand forecasting, promotional lift, pricing elasticity); SLB/Schlumberger (MLOps, quantitative pricing); Taager (Dubai, 2023) — AraBERT-based Arabic NER for MENA e-commerce; GE HealthCare (intern May–Oct 2025; current role since Dec 2025).
- Awards: 2nd place, QRT Data Challenge (as part of a team); 2nd place, BCG X Datathon.
- Community: Team Lead for AI/AGI at Automaton; campus ambassador for QRT; runs student workshops; co-organizes hackathons with IBM, QRT, and BCG X.
- Languages: trilingual Arabic (MSA + Moroccan Darija), French, English — directly relevant to this project.
- Relevant skills: transformers, multilingual NLP, entity resolution, knowledge graphs, Bayesian inference, RL/POMDP, MLOps, data pipelines, UI/UX.
- Open-source experience: `[List your merged PRs and links here. If you cannot yet, this is your top pre-application priority — land 2–4 genuine PRs in DBpedia repos first. Never list contributions you have not actually made.]`

#### Short alternative outline (for #2: ML4SCI — medical-imaging ML)

- **Target idea:** a PREDICT medical-imaging project (e.g., Coronary Artery Calcium (CAC) segmentation or radiomics feature extraction) — directly adjacent to your GE HealthCare MRI/CT experience.
- **Title** (example): Robust Segmentation and Uncertainty-Aware Scoring for Coronary Artery Calcium in CT.
- **Synopsis:** improve CAC segmentation/scoring with modern (transformer/CNN) models plus calibrated uncertainty — connecting your medical-imaging domain knowledge and Bayesian background.
- **WBS:** investigation → data/pre-processing → model → evaluation vs. baseline → uncertainty/calibration (optional) → tests → docs.
- **Process differences vs. DBpedia:** apply to a listed project with a mentor; complete the project's evaluation test; engage via ml4-sci@cern.ch / Gitter / project GitHub. 175h projects fit your schedule.
- **Positioning:** lead with your MRI/CT domain experience — a genuine, verifiable strength.

## Recommendations

1. **Commit to DBpedia now** (primary) with ML4SCI as backup. Both fit your profile truthfully; DBpedia's KG + multilingual-NLP focus plus its openness to original ideas is the single best strategic bet, and ML4SCI's medical-imaging track hedges toward your GE HealthCare domain. Threshold to switch: if DBpedia is not on the February 2027 accepted-orgs list, promote ML4SCI to primary and add Apache Beam as the data-engineering backup.
2. **Clear the three gating items** in September–October 2026 before investing effort: (a) France work-eligibility, (b) GE HealthCare contract (outside-work/stipend/IP), (c) a completed public GitHub profile. If the contract check is not clean, resolve it in writing before contributing code.
3. **Build a genuine contribution record** between October 2026 and February 2027. Land 3–4 of your own small merged PRs — start with DBpedia extraction-framework issues #760 (non-Latin script — plays to your Arabic strength), #825, or #819, then move to a Python fix in the Neural Extraction Framework. This is the highest-leverage action; prior mentor interaction is officially "the most critical factor."
4. **Engage mentor @tsoru early** (December–January) with your Arabic-chapter concept to confirm mentor availability — a project without a willing mentor is the most common way original proposals fail.
5. **Default to a Medium (~175h) project.** Only pitch a Large (350h) project if, by January 2027, your PhD calendar clearly has the capacity and the mentor endorses the larger scope with a possible timeline extension.
6. **Write the proposal yourself**, submit early as a PDF, and disclose any research-only AI use. Share a draft weeks before the deadline; never rely on getting an extension — there are none.
7. **Be scrupulously accurate:** "team" for the QRT award, "submission/ongoing" for the papers, and only real, linkable PRs in the open-source section. Misrepresentation is disqualifying and Google verifies eligibility.

## Caveats

- GSoC 2027 dates are not yet published (as of 22 Sep 2026); all 2027 dates here are estimates extrapolated from the confirmed 2026 calendar. Confirm on the official site.
- Org participation is re-decided every year. DBpedia, ML4SCI, NumFOCUS/PyMC, Apache, Farama, and DeepChem all participated recently, but none is guaranteed to return in 2027. Confirm when the accepted-orgs list is published.
- The stipend for France is an estimate based on the PPP methodology and published ranges; the exact France figure appears on Google's annual country chart — verify for 2027.
- DBpedia's AI policy could not be confirmed from public sources; ask on the forum before relying on any AI assistance.
- Beginner issues are live tickets and may be closed or claimed by the time you read this; re-check before starting, and always comment/get sign-off first. The extraction-framework is Scala/Java; the Neural Extraction Framework is Python.
- Your GitHub profile / prior open-source PRs were not independently verified in this research; a profile at github.com/Abdelaziz03 appears to match you but was not confirmed. Fill in real handles and real contributions only.
- **Do not fabricate anything.** Every award (team vs. individual), paper (submission vs. accepted), and contribution must be stated exactly as it is — this protects you, since mentors and Google verify.
