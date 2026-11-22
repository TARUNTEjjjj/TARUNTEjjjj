<!--
  The images below are generated: edit profile.json (banner text, tech stack) and the
  "Build profile" workflow redraws them. `python3 scripts/build.py` redraws the banner and
  stack locally. The activity card is not shown here, so the workflow no longer draws it;
  scripts/build.py explains how to preview it or bring it back.
-->

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/header-dark.svg">
  <img alt="Tarun Tej — Python Programmer, AI/ML Learner and AI Code Evaluator" src="assets/header-light.svg" width="100%">
</picture>

## About me

**Python Programmer · AI/ML Learner · AI Code Evaluator**

I'm Tarun Tej. I write **Python for machine learning and scientific computing (NumPy, PyTorch, scikit-learn)**, explore mathematical systems, and build interactive web applications with **React, TypeScript, and Three.js**. My work includes reproducible neural-network experiments from first principles, an interactive weather-evidence 3D globe, and exact arithmetic systems.

At Outlier and Mercor, I perform **Side-by-Side (SxS) model evaluations, AI code reviews, and adversarial prompt engineering** to test reasoning depth, instruction adherence, and code correctness for frontier LLMs. I am looking for entry-level opportunities in **Python programming, AI/ML engineering, AI code evaluation, and software development**.

[Visit my portfolio](https://tarun-tej.pages.dev/) · [Browse my repositories](https://github.com/TARUNTEjjjj?tab=repositories)

## Featured projects

### StormSignal · weather with evidence

[![StormSignal in Full workspace: the 3D globe shows NASA's 18 November 2026 satellite mosaic over North America, with New York City selected](https://raw.githubusercontent.com/TARUNTEjjjj/stormsignal/main/docs/images/aurora-globe-desktop.jpg)](https://stormsignal-weather.pages.dev/)

A weather workspace that puts forecasts, satellite imagery, model disagreement and official warning coverage in one view, and never treats missing data as an all-clear.

**React 19 · TypeScript · three.js / WebGL 2 · Cloudflare Pages Worker · Leaflet · NASA GIBS**

- **Interactive 3D globe:** NASA's newest finished daily satellite mosaic, with its date and coverage stated, day and night drawn from the sun's position, and active official warning outlines. It works fully by keyboard, and three.js loads only in Full workspace on browsers with WebGL 2.
- **Official warnings with their limits shown:** the US National Weather Service, read straight from the browser, plus PAGASA (Philippines), BMKG (Indonesia), IMD's Kolkata district nowcast, India's regional SACHET feeds and participating WMO authorities through the project's own Cloudflare Worker gateway. An unreachable source is reported as unavailable.
- **Three modes for weak connections:** Data saver (default; no 3D or background polling), Full workspace (globe, maps and reports) and Offline only (dated saved briefings and a self-contained field kit).
- **Interactive forecast explorer:** inspect any hour by pointer or keyboard, read the exact values, compare two models and export CSV.
- **Engineering record:** 708 application tests, including scene tests on real three.js and a test-only GLSL interpreter that runs the globe's surface shader on the CPU; accessibility tests tied to specific WCAG criteria (contrast, visible focus, pausable motion, controls that need no drag); and a dated verification record that states what was and was not tested.

[Try StormSignal](https://stormsignal-weather.pages.dev/) · [Read the source](https://github.com/TARUNTEjjjj/stormsignal) · [UI case study](https://github.com/TARUNTEjjjj/stormsignal/blob/main/docs/ui-case-study.md) · [Verification record](https://github.com/TARUNTEjjjj/stormsignal/blob/main/docs/verification.md)

### Neural Math Lab · neural networks from first principles

[![Training and validation loss in the Neural Math Lab moons experiment](https://raw.githubusercontent.com/TARUNTEjjjj/neural-math-lab/main/examples/moons/learning.svg)](https://neural-math-lab.pages.dev/)

Understand neural network mechanics from core mathematical formulations rather than opaque abstractions. Neural Math Lab implements forward propagation, backpropagation, and optimization algorithms directly in NumPy.

**Python · NumPy · scikit-learn · Optimization (SGD & Adam) · Cloudflare Pages**

- **First-principles mathematics:** Explicit tensor equations for Sigmoid, Tanh, and ReLU activations, numerical derivative validation with analytical gradient checks, and stable saturation tail calculations.
- **Reproducible experiment suite:** Interactive decision boundary and learning curve reports for benchmark datasets (Moons, Concentric Circles, XOR, and real-world Iris measurements).
- **In-depth diagnostics:** Real-time checkpoint replay, input-sensitivity derivatives, decision cost surfaces, and baseline comparisons against logistic regression.
- **Zero-dependency portability:** Every experiment report is fully self-contained HTML/SVG, runnable completely offline without internet or server requirements.

[Try Neural Math Lab](https://neural-math-lab.pages.dev/) · [Read the source](https://github.com/TARUNTEjjjj/neural-math-lab)

## More of what I'm building

| Area | Project | Work to explore |
| --- | --- | --- |
| **Mathematics practice** | [Axiom SAT Math](https://github.com/TARUNTEjjjj/axiom-sat) · [Live app](https://axiom-sat.pages.dev/) | Free SAT-style math practice with 31 seeded reproducible templates, timed sessions, browser-saved progress, and Playwright verification. |
| **AI learning interfaces** | [Attention Atlas](https://github.com/TARUNTEjjjj/attention-atlas) · [Live guide](https://attention-atlas.pages.dev/) | Interactive CNN, RNN and Transformer mathematics with editable inputs, matrix calculations and explanations. |
| **Systems programming** | [PocketKV](https://github.com/TARUNTEjjjj/pocketkv) | A persistent C++20 key-value store with an append-only log, checksums, file locking, snapshots and recovery. |
| **Mathematics and C++** | [AxiomMath](https://github.com/TARUNTEjjjj/axiom-math) | Exact rational arithmetic and expression parsing with explicit overflow bounds and differential checks against Python's `fractions.Fraction`. |
| **Web and assessment tools** | [Avenquellis](https://github.com/TARUNTEjjjj/avenquellis-web) · [Question engine](https://github.com/TARUNTEjjjj/avenquellis-question-engine) · [Proof grader](https://github.com/TARUNTEjjjj/avenquellis-proof-grader) | A mathematics workspace using C++/WebAssembly, reproducible questions and bounded proof-certificate checks. Free-form model assessments remain proposals for human review. |
| **Learning applications** | [Vedaris JEE](https://github.com/TARUNTEjjjj/vedaris-jee) · [Live workspace](https://vedaris-jee.pages.dev/) | Timed practice, historical-paper sessions, worked review, validated content and recoverable browser-local progress. |

Other work: [Forge](https://github.com/TARUNTEjjjj/forge-learning-academy) for browser-based Python and Git exercises; and [Forge for Mac](https://github.com/TARUNTEjjjj/forge-macos), a native SwiftUI study workspace.

## Tech stack

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/stack-dark.svg">
  <img alt="Tech stack: Python, C++, C, NumPy, pandas, PyTorch, scikit-learn, React, TypeScript, JavaScript, HTML5, CSS, Node.js, Git, GitHub" src="assets/stack-light.svg" width="100%">
</picture>

## GitHub activity

For reviewable work, start with [StormSignal's commits](https://github.com/TARUNTEjjjj/stormsignal/commits/main/) and [pull requests](https://github.com/TARUNTEjjjj/stormsignal/pulls?q=is%3Apr). The contribution graph records activity; code, explanations and verification provide the context behind it.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/snake-dark.svg">
  <img alt="A snake eating Tarun Tej's contribution graph" src="assets/snake-light.svg" width="100%">
</picture>

<p align="right"><sub>Cards drawn by <a href="scripts/build.py">scripts/build.py</a> and refreshed daily by GitHub Actions · most logos via <a href="https://simpleicons.org">Simple Icons</a> (C++, Python and pandas: their owners' official logos); HTML5 logo by W3C and Git logo by Jason Long, <a href="https://creativecommons.org/licenses/by/3.0/">CC BY 3.0</a> · <a href="THIRD_PARTY_NOTICES.md">all credits</a></sub></p>

<details>
<summary>Preview and validate profile cards locally</summary>

Run `python3 scripts/build.py --check` to render and validate the banner and
stack without changing files. Use `--output-dir /path/to/preview` for a separate
preview directory, and `--data scripts/sample-stats.json` to include activity
cards without network access; that sample shows the snapshot format. A `--data`
preview goes to `preview/`, which git ignores, unless `--output-dir` names
another directory, and never into `assets/`. `--today YYYY-MM-DD` chooses the
day, by default the snapshot's last one. The chosen day bounds contribution
calendar totals and streaks; other aggregate counts retain the snapshot values.
All cards are rendered and checked as SVG before any are written, and individual
files are replaced atomically. `python3 -m unittest discover -s tests -v` exercises
these offline paths; pull requests run the same checks without a write token.

</details>

## GitHub resource collection

Explore the project-specific [resource catalog](resources/README.md): curated references, star-ranked discovery, dated source metadata, cached failure recovery and an optional read-only server API. The repository includes a daily refresh workflow; hosted sites still follow their existing deployment process.
