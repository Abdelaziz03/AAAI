# From scrap to value: knowledge, learning and optimisation for the disposition of scrapped units

*Formal framework of the project. Working document for a journal submission; written in English because the target venues are. The team-facing French description of the line model is `Modele_mathematique.md`.*

**How to read the status marks.** Every statement carries one of five marks.

| Mark | Meaning |
|---|---|
| **[proved]** | A proof is given here. The result is also checked numerically where a test is named. |
| **[implemented]** | Coded in the package and covered by tests; the module is named. |
| **[not implemented]** | Stated or proved here, not coded. |
| **[literature]** | Established elsewhere; the reference is given. We do not re-prove it and do not claim it transfers to our setting unless stated. |
| **[to measure]** | A claim that needs field data. Nothing in this document is an empirical result: every number in the repository comes from fictional demonstration data. |

**Review.** The propositions, their proofs, the references and the code of Section 8 were checked by three independent automated reviews: language-model agents that were given the document and the code, not the author's reasoning, and that also tried to break each proposition numerically. Their corrections are incorporated: one corollary was wrong by one (Section 9), two bounds were loose or miscoded (Proposition 6), the fusion rule of Section 8.2 treated a yes/no check inconsistently, and the positioning overstated novelty (Section 11). No human referee has read this document; an automated review is not peer review.

---

## 1. Problem and scope

A repair centre for medical equipment receives field-replaceable units (FRUs). Some are repaired; the others are **scrapped** and today leave whole through a bulk waste contract that produces no revenue. Each scrapped unit still contains components that could be (i) **reused** in repairs after extraction and test, (ii) **repaired or remanufactured**, (iii) **sorted** and sold by the kilogram to a specialised recycler, or (iv) left in the unit (status quo). Extraction takes operator time that is not in the current workload, opening a unit is a set-up paid once per unit, the share of components that are still good is unknown, the flow of scrapped units is irregular, and the material composition of most components, which determines recycling prices and regulatory routes, is not recorded anywhere.

The decision problem has three layers:

1. **Disposition.** For each type of scrapped unit, whether to open it, and what to do with each component, under a labour budget (Sections 3 and 4).
2. **Learning and forecasting.** Estimating the yields that drive the reuse value, and the arrivals that drive the workload, while decisions are being taken (Sections 5 to 7).
3. **Knowledge acquisition.** Deciding which missing facts (compositions, yields) are worth acquiring, and by which means, given what each costs (Section 8).

The same structure appears in **production**: a nonconforming assembly at a production stage is a scrapped unit; its sub-assemblies can be reworked, harvested for new builds, or sorted by material. Section 10 gives the correspondence. The model is therefore written for abstract *unit types*, *components*, *dispositions*, *access levels* and *resources*, and an application is a data instance.

**Position in the literature.** Product recovery options (reuse, repair, remanufacturing, cannibalisation, recycling) are classified by Thierry et al. (1995); quantitative models are reviewed by Fleischmann et al. (1997) and Guide and Van Wassenhove (2009). Choosing how far to disassemble a product and which recovery option to apply to each sub-assembly is the recovery-strategy problem of Krikke, van Harten and Schuur (1998), extended to several disassembly processes and to partial disassembly by Teunter (2006). Meacham, Uzsoy and Venkatadri (1999) optimise the disassembly configuration of one product and then, by column generation, how many units of each product follow each configuration; that programme has the form of our problem (P). Random yields of good parts from disassembled cores are treated by Inderfurth and Langella (2006); the value of knowing yields before deciding by Ferrer and Ketzenberg (2004) and Ketzenberg, van der Laan and Teunter (2006); the choice between remanufacturing a return and dismantling it for spare parts by Ferguson, Fleischmann and Souza (2011), in the setting described by Fleischmann, van Nunen and Gräve (2003) of returned equipment as a source of service parts, which is the closest to a repair centre; grading of returns by condition by Ferguson et al. (2009); and learning-based disassembly planning under uncertain part quality by Reveliotis (2007). These descriptions rest on the abstracts and records of the papers; the full texts have not been read for this document. Section 11 states what the document adds to them, and with what confidence.

**Why it matters beyond cost [to measure].** Reused and repaired parts lower the cost of keeping imaging systems running and of refurbishing them, which is one of the levers for access to imaging in hospitals with small budgets; sorted streams keep critical raw materials in use. Section 9 states these outcomes as measurable quantities. The framework makes no claim about their size.

---

## 2. Notation

Each symbol has one meaning in the whole document. Periods are indexed by $k$; the letter $t$ is kept for operator times.

**Sets.**

| Symbol | Meaning |
|---|---|
| $\mathcal{I}$ | types of scrapped unit |
| $\mathcal{J}_i$ | components of a unit of type $i$ |
| $\mathcal{D}$ | dispositions of a component; $0 \in \mathcal{D}$ is "leave in the unit" |
| $\mathcal{L} = \{0, 1, \dots, L\}$ | access levels of a unit, ordered; $0$ = not opened |
| $\mathcal{S}_i = \mathcal{D}^{\mathcal{J}_i}$ | plans for a unit of type $i$: one disposition per component; $s^0$ = all components left |
| $k = 1, \dots, T$ | periods |
| $\mathcal{C}$ | material classes of the reference list; $\bar{\mathcal{C}} = \mathcal{C} \cup \{\varnothing\}$, where $\varnothing$ stands for "a class outside the list" |

**Data of the static problem** (one period; the period index is dropped).

| Symbol | Meaning |
|---|---|
| $N_i \ge 0$ | scrapped units of type $i$ available |
| $n_{ij} \ge 1$ | copies of component $j$ in a unit of type $i$ |
| $N^{c}_j = \sum_{i \,:\, j \in \mathcal{J}_i} N_i\, n_{ij}$ | copies of component $j$ in the scrapped units of the period, all types together |
| $\ell_d \in \mathcal{L}$ | access level that disposition $d$ requires; $\ell_0 = 0$ |
| $a_{i\ell} \ge 0$ | time to open a unit of type $i$ to level $\ell$; $a_{i0} = 0$ |
| $t_{jd} \ge 0$ | operator time per copy of $j$ under disposition $d$; $t_{j0} = 0$ |
| $\rho_{ijd}$ | net value per copy of $j$ under $d$, before labour; $\rho_{ij0} = 0$ |
| $w_i \ge 0$ | cost of an operator hour on type $i$ |
| $H \ge 0$ | operator hours available |
| $K \ge 0$ | fixed cost of the line for the period (amortised investment plus fixed costs) |

For a plan $s \in \mathcal{S}_i$, the induced access level, the hours and the margin per unit are

$$\ell(s) = \max_{j \in \mathcal{J}_i} \ell_{s_j}, \qquad h_{is} = a_{i\,\ell(s)} + \sum_{j} n_{ij}\, t_{j s_j}, \qquad g_{is} = \sum_{j} n_{ij}\, \rho_{i j s_j} - w_i\, h_{is},$$

with $\ell(s) = 0$ when $\mathcal{J}_i$ is empty. The plan $s^0$ has $h_{i s^0} = 0$ and $g_{i s^0} = 0$: the status quo is the reference and is worth zero.

**The instance used in the repair centre.** Three dispositions: reuse ($\mathsf{R}$, level 2), sorted recycling ($\mathsf{S}$, level 1), leave ($0$). Let $q_{ij}$ be the probability that an extracted copy is reusable, $v_j$ the value of a reused copy, $\Lambda_j$ the value of the procurement lead time that a reused copy avoids, $\bar v_j = v_j + \Lambda_j$, $\kappa_j$ the transport cost, $m_j$ the mass of a copy, $p_j$ the price paid by the recycler for its class, and $\tau$ the cost per kilogram of the current bulk treatment (negative if the current contractor pays). Then

$$\rho_{ij\mathsf{R}} = q_{ij}\,\bar v_j + (1 - q_{ij})\, m_j p_j + \tau m_j - \kappa_j, \qquad \rho_{ij\mathsf{S}} = m_j\,(p_j + \tau),$$

$$t_{j\mathsf{R}} = t^{\text{ext}}_j + t^{\text{test}}_j, \qquad t_{j\mathsf{S}} = t^{\text{sort}}_j .$$

With complete data, a copy that fails its test is sold by the kilogram and every copy taken out of the unit avoids the bulk treatment. **[implemented]** `erc/ligne.py`, `valeurs_options`; the formulas agree with the code to rounding on random draws.

*When data are missing.* The class of a component fixes its price. When $p_j$ is unknown and $m_j$ known, sorting $j$ is not available, a failed copy returns to the bulk stream, and $\rho_{ij\mathsf{R}} = q_{ij}\,(\bar v_j + \tau m_j) - \kappa_j$. When $m_j$ is unknown, sorting is not available and $\rho_{ij\mathsf{R}} = q_{ij}\,\bar v_j - \kappa_j$. The omitted terms are reported (column *Non compté faute de donnée*); an unknown is never replaced by zero silently. We write $\varnothing_j$ for "the class of $j$ is not established", that is, $p_j$ unknown.

---

## 3. The disposition problem

Let $x_{is} \ge 0$ be the number of units of type $i$ processed with plan $s$.

$$
\begin{aligned}
V(N, H) \;=\; \max_{x \ge 0} \quad & \sum_{i \in \mathcal{I}} \sum_{s \in \mathcal{S}_i} g_{is}\, x_{is} \\
\text{s.t.} \quad & \sum_{s \in \mathcal{S}_i} x_{is} = N_i \qquad \forall i \in \mathcal{I}, \\
& \sum_{i \in \mathcal{I}} \sum_{s \in \mathcal{S}_i} h_{is}\, x_{is} \le H .
\end{aligned}
\tag{P}
$$

The line is installed if $V(N, H) > K$; the gain over the status quo is $V(N,H) - K$.

(P) is the linear relaxation of a multiple-choice knapsack problem (Sinha and Zoltners 1979; Zemel 1980): each type is a class, each plan an item, the labour budget the knapsack. The relaxation is the natural model here because $N_i$ counts many identical units; Remark 1 bounds what integrality costs. (P) is always feasible ($x_{i s^0} = N_i$) and bounded.

**Assumption A1 (nested access).** $0 = a_{i0} \le a_{i1} \le \dots \le a_{iL}$ for every $i$: opening a unit further never takes less time. A1 is used only in Proposition 1.

**Assumption A2 (linearity).** Times and values are proportional to the number of units; there is no learning effect and no minimum lot.

**Assumption A3 (independence across components).** The state of a component does not depend on the state of the others in the same unit. A type-level correction factor absorbs the average effect of a unit having been scrapped (Section 5).

---

## 4. Structure of the solution

### 4.1 Lagrangian dual and the value of an hour

For $\mu \ge 0$ let $\varphi_i(\mu) = \max_{s \in \mathcal{S}_i} \,(g_{is} - \mu h_{is})$ be the best *reduced margin* of a unit of type $i$ when an operator hour is priced at $\mu$ on top of its cost.

**Proposition 1 (pricing by access level) [proved].** Under A1, for every $i$ and $\mu \ge 0$, with $\omega_i = w_i + \mu$,

$$\varphi_i(\mu) \;=\; \max_{\ell \in \mathcal{L}} \Big\{ -\,\omega_i\, a_{i\ell} \;+\; \sum_{j \in \mathcal{J}_i} \; \max_{d \,:\, \ell_d \le \ell} \; n_{ij}\,\big(\rho_{ijd} - \omega_i\, t_{jd}\big) \Big\}.$$

The pricing problem of a type is therefore solved in $O(|\mathcal{J}_i|\,|\mathcal{D}|\,L)$ operations, without enumerating its $|\mathcal{D}|^{|\mathcal{J}_i|}$ plans.

*Proof.* Write $G_i(\ell)$ for the term in braces. ($\le$) Let $s$ be any plan and $\ell = \ell(s)$. Every $s_j$ satisfies $\ell_{s_j} \le \ell$, so $n_{ij}(\rho_{ijs_j} - \omega_i t_{js_j})$ is at most the inner maximum, and $g_{is} - \mu h_{is} = -\omega_i a_{i\ell} + \sum_j n_{ij}(\rho_{ijs_j} - \omega_i t_{js_j}) \le G_i(\ell)$. ($\ge$) Fix $\ell$ and let $s^\ell$ pick, for each $j$, a maximiser of the inner problem. Then $\ell(s^\ell) \le \ell$, hence $a_{i\,\ell(s^\ell)} \le a_{i\ell}$ by A1, and since $\omega_i \ge 0$, $g_{is^\ell} - \mu h_{is^\ell} \ge G_i(\ell)$. $\blacksquare$

A1 is necessary for the formula: when a rough opening takes longer than a careful one, the right-hand side can overstate $\varphi_i$.

**Remark (two levels, without A1) [proved, implemented].** In the instance of Section 2 a plan is opened carefully as soon as one component is reused, and roughly as soon as one is sorted and none reused. Writing $\Psi^{d}_j = n_{ij}(\rho_{ijd} - \omega_i t_{jd})$ for $d \in \{\mathsf R, \mathsf S\}$ and $x^+ = \max(x, 0)$,

$$\varphi_i(\mu) = \max\Big\{0,\;\; -\omega_i a_{i1} + \sum_j (\Psi^{\mathsf S}_j)^+ ,\;\; -\omega_i a_{i2} + \sum_j \max(\Psi^{\mathsf R}_j, \Psi^{\mathsf S}_j, 0) \;-\; \min_j \big(\max(\Psi^{\mathsf S}_j, 0) - \Psi^{\mathsf R}_j\big)^+ \Big\},$$

where the second term is kept only if some $\Psi^{\mathsf S}_j \ge 0$. The three terms are the best plans with no opening, with sorting only, and with at least one reuse; in the last, each component takes its best disposition, and if none chooses reuse it is imposed on the component for which it costs least. No ordering of $a_{i1}$ and $a_{i2}$ is used. This is what the code computes for a type with more than eight components; up to eight, plans are enumerated. `erc/ligne.py`, class `Options`; the two methods agree on random types with missing data, negative $\tau$ and $a_{i1} > a_{i2}$, and the resulting optimum equals that of an exact solver on types of nine and ten components (`tests/test_ligne.py`). The browser tool carries the same method (`erc/outil_modele.js`).

**Proposition 2 (dual and value function) [proved].**

$$V(N, H) \;=\; \min_{\mu \ge 0} \Big\{ \mu H + \sum_{i \in \mathcal{I}} N_i\, \varphi_i(\mu) \Big\}.$$

$V$ is concave, piecewise linear and positively homogeneous of degree one in $(N, H)$, and nondecreasing in each argument. If $\mu^\ast$ attains the minimum, then $V(N, H') \le V(N, H) + \mu^\ast (H' - H)$ for every $H' \ge 0$. Any optimal $\mu^\ast$ lies between the value of one more operator hour (the right derivative of $V$ in $H$) and the loss from one hour less (the left derivative); the two coincide except at the finitely many breakpoints of $V$, and $\mu^\ast = 0$ is optimal when the labour budget is not exhausted.

*Proof.* Dualise the capacity constraint with multiplier $\mu \ge 0$; the remaining problem separates by type and its value is $N_i \varphi_i(\mu)$ since all of $N_i$ goes to a best plan. Strong duality holds because (P) is a feasible bounded linear programme. The optimal value of a maximisation linear programme is concave and piecewise linear in its right-hand side, and positive homogeneity follows from scaling $x$. Monotonicity in $H$ is the relaxation of a constraint; monotonicity in $N_i$ holds because additional units can be assigned $s^0$ at no cost. The inequality is the supergradient property of the dual solution: for any $H'$, weak duality gives $V(N, H') \le \mu^\ast H' + \sum_i N_i \varphi_i(\mu^\ast) = V(N, H) + \mu^\ast(H' - H)$; applied to $H' > H$ and $H' < H$ it places $\mu^\ast$ between the two one-sided derivatives. $\blacksquare$

The dual objective is convex and piecewise linear in $\mu$, with subgradient $H - \sum_i N_i h_{i s_i(\mu)}$ at any selection $s_i(\mu)$ of best plans. Pricing the budget and solving the separable problem for a given multiplier is the generalised Lagrange multiplier method of Everett (1963). The implementation locates $\mu^\ast$ by bisection on the sign of this subgradient, recovers a primal solution by Proposition 3, and returns the value of one more hour. **[implemented]** `erc/ligne.py`, `optimiser_ligne`; the optimal value equals that of an exact LP solver (HiGHS) within $10^{-6}$ on 600 random instances, and the multiplier is bracketed by the left and right finite-difference slopes of $V$ (`tests/test_ligne.py`).

### 4.2 Shape of an optimal solution

**Proposition 3 (few split types, efficient plans) [proved].** (P) has an optimal solution in which every type with $N_i > 0$ uses one plan, except at most one type, which uses two. In any optimal solution, with $\mu^\ast$ an optimal multiplier, every plan in use attains $\varphi_i(\mu^\ast)$; in particular it lies on the upper concave envelope of the points $\{(h_{is}, g_{is})\}_{s \in \mathcal{S}_i}$, and the two plans of a split type lie on a common edge of that envelope, of slope $\mu^\ast$. More generally, with $M$ coupling constraints in place of the single labour budget, a feasible programme has an optimal solution in which at most $M$ types use more than one plan.

For a single budget this is the classical structure of the linear multiple-choice knapsack problem (Sinha and Zoltners 1979; Zemel 1980) **[literature]**; the proof is given for completeness and for $M$ coupling constraints.

*Proof.* Types with $N_i = 0$ have all their variables equal to zero; delete them, and let $\mathcal{I}^+ = \{i : N_i > 0\}$. Add a slack to each coupling constraint. The programme has $|\mathcal{I}^+| + M$ equality constraints, so an optimal basic solution, which exists because the programme is feasible and bounded, has at most $|\mathcal{I}^+| + M$ positive variables. Each type of $\mathcal{I}^+$ needs at least one positive plan variable, which leaves at most $M$ further positive variables, hence at most $M$ types with a second plan. For the second claim let $(\zeta, \mu^\ast)$ be optimal dual variables: dual feasibility reads $\zeta_i \ge g_{is} - \mu^\ast h_{is}$ for all $s$, and complementary slackness gives equality whenever $x_{is} > 0$. So a plan in use maximises $g_{is} - \mu^\ast h_{is}$ over $\mathcal{S}_i$, that is, the line of slope $\mu^\ast$ through $(h_{is}, g_{is})$ supports the point set from above. Two plans of the same type in use lie on the same supporting line. $\blacksquare$

**Remark 1 (integrality).** With a single budget, rounding the split type down to whole units and sending the remainder to the cheaper of its two plans keeps the solution feasible and loses less than the margin difference of one unit. With hundreds of units per type the relaxation is immaterial. The argument holds for $\le$ constraints only; a lower bound on an outcome (Section 9) can be violated by rounding down.

**Managerial reading.** At the optimum, a single number, the value of an hour $\mu^\ast$, coordinates all decisions: every type is processed with the plan that is best when labour is charged $w_i + \mu^\ast$, and at most one type is processed in two ways because the hours run out part-way through it.

### 4.3 A threshold rule for reuse

Specialise to the three dispositions of Section 2 and consider a unit that is opened to level 2 anyway. The choice is then separable across components.

**Proposition 4 (yield threshold) [proved].** Let $\omega = w_i + \mu$ and assume $\bar v_j > m_j p_j$ (a good copy is worth more reused than as material). In a unit opened to level 2, reuse is at least as good as both sorting and leaving component $j$ if and only if

$$q_{ij} \;\ge\; q^{\dagger}_{ij}(\mu) \;=\; \frac{\kappa_j + \omega\, t_{j\mathsf{R}} - \min\{\omega\, t_{j\mathsf{S}},\; m_j (p_j + \tau)\}}{\bar v_j - m_j p_j}.$$

When $t_{j\mathsf{R}} \ge t_{j\mathsf{S}}$ the threshold is nondecreasing in $\mu$: the scarcer the labour, the higher the yield a component must show to be worth extracting and testing.

*Proof.* Per copy, the reduced values are $\psi^{\mathsf{R}} = q\bar v + (1-q) m p + \tau m - \kappa - \omega t_{\mathsf R}$, $\psi^{\mathsf{S}} = m(p + \tau) - \omega t_{\mathsf S}$ and $\psi^{0} = 0$ (indices dropped). $\psi^{\mathsf R} \ge \psi^{\mathsf S}$ rearranges to $q(\bar v - mp) \ge \kappa + \omega(t_{\mathsf R} - t_{\mathsf S})$, and $\psi^{\mathsf R} \ge 0$ to $q(\bar v - mp) \ge \kappa + \omega t_{\mathsf R} - m(p+\tau)$. Both hold if and only if $q(\bar v - mp)$ is at least the larger right-hand side, which is $\kappa + \omega t_{\mathsf R} - \min\{\omega t_{\mathsf S}, m(p+\tau)\}$; divide by $\bar v - mp > 0$. For monotonicity, the slope of the numerator in $\omega$ is $t_{\mathsf R} - t_{\mathsf S} \ge 0$ where the minimum is $\omega t_{\mathsf S}$ and $t_{\mathsf R} \ge 0$ elsewhere. $\blacksquare$

Both hypotheses are needed: the comparison reverses when $\bar v_j \le m_j p_j$, and the threshold can decrease in $\mu$ when $t_{j\mathsf R} < t_{j\mathsf S}$.

The rule is what an operator can apply at the bench: *extract and test component $j$ when its observed good rate is above $q^\dagger_{ij}$*. The threshold is conditional on the unit being opened carefully; whether it is opened at all is decided by Proposition 1, where the opening set-up is weighed against the sum of the components' reduced values.

---

## 5. Unknown yields: learning while deciding

### 5.1 Model

The yield $q_{ij}$ is unknown. It is given a Beta prior whose mean comes from consumption records. Let $\nu_i$ be the number of repairs of type $i$ in the records, $\mathrm{cons}_{ij}$ the copies of $j$ consumed in them, and $\eta_j$ the share of replacements made as a precaution. The probability that a copy is defective in a *repaired* unit is estimated by $\hat\delta_{ij} = (1 - \eta_j)\,\mathrm{cons}_{ij} / (\nu_i\, n_{ij})$, and

$$q^0_{ij} = \big(1 - \gamma_i\, \hat\delta_{ij}\big)_{[0,1]}\,(1 - \chi_j)\, \vartheta_j ,$$

with $\gamma_i \ge 1$ a factor for scrapped units being in worse condition than repaired ones, $\chi_j$ the breakage at extraction and $\vartheta_j$ the share of sound copies that pass the test. Teardown audits and routine tests then give binomial observations: of $z$ copies tested, $y$ are good. With prior $\text{Beta}(q^0 \varpi, (1 - q^0) \varpi)$, where $\varpi$ is the weight of the prior in equivalent tested copies, the posterior is $\text{Beta}(q^0 \varpi + y,\ (1 - q^0) \varpi + z - y)$. **[implemented]** `erc/rex.py`, `erc/parametres.py::a_priori_rex`.

The prior is a modelling assumption with three identified weaknesses, all of which bias it in a known direction and are corrected by audit data: preventive replacement inflates $\hat\delta$; scrapped units are worse than repaired ones ($\gamma_i$ is not identified without an audit); and repairs that consumed nothing are missing from $\nu_i$.

### 5.2 The exploration problem

A copy's state is observed only if it is extracted and tested. A rule that follows the posterior mean never tests a component whose prior mean is below the threshold of Proposition 4, and therefore never corrects a pessimistic prior. This is a combinatorial semi-bandit: in each period the decision is a feasible point of (P), whose labour budget is renewed, the reward is affine in the unknown yields, and the outcome of each tested copy is observed.

**Algorithm TS-LP [implemented].** In each period: (1) draw $\tilde q_{ij}$ from the current posterior of every $(i,j)$; (2) solve (P) with $\tilde q$; (3) process the units accordingly; (4) update the posteriors with the test outcomes. `erc/rex.py::plan_thompson`.

Thompson sampling for combinatorial semi-bandits is analysed by Wang and Chen (2018), and posterior sampling in general by Russo and Van Roy (2014). Sampling from the posterior and then solving a linear programme is also the scheme of Ferreira, Simchi-Levi and Wang (2018) for network revenue management; there, as in bandits with knapsacks (Badanidiyuru, Kleinberg and Slivkins 2018), the inventory or budget is consumed over the whole horizon, which is not our case. **[literature]** We have not checked that the assumptions of Wang and Chen cover our instance (a component is observed only when it is reused, the number of observations depends on the plan, and the arrivals vary), so we claim **no** bound. With $x_k$ the plan of period $k$ and $N_k$ its arrivals, regret is defined as

$$\text{Regret}(T) = \sum_{k=1}^{T} \Big( V(N_k, H; q) - \mathbb{E}\big[\,g(q)^{\top} x_k\,\big] \Big),$$

and is evaluated numerically. On a one-component synthetic benchmark with a prior mean of 0.2, a true yield of 0.6 and a threshold of 0.27, the rule that follows the prior and the greedy rule never test the component and lose 17.2 per copy, while Thompson sampling tests 96 % of copies, recovers an estimate of about 0.59 and loses about 0.65 per copy. These are simulation figures in arbitrary monetary units, not field results. **[implemented]** `erc/rex.py::simuler_politiques`. Extending the benchmark to full instances of (P) is planned, as is a comparison with a knowledge-gradient policy, which Frazier, Powell and Dayanik (2008) analyse for offline ranking and selection with normal beliefs and which must be adapted here to Beta-Bernoulli yields and cumulative reward.

### 5.3 How the estimate is evaluated

The posterior is scored prequentially: each audit batch is predicted from what was known before it and only then used for updating. Reported: Brier score and logarithmic loss for grouped binomial outcomes, absolute error on the batch rate, and coverage of the 90 % predictive interval (Beta-binomial). Two references must be beaten: the prior alone, and the raw observed frequency. **[implemented]** `erc/rex.py::evaluer`; a test checks that a batch cannot influence its own prediction (`tests/test_stats.py`).

### 5.4 Quality of reused parts in service

A reusable part must also last once installed. The available field file records only early failures within a window of $W$ days after installation, in whole days, with no survivors. From such data the Weibull shape is estimable by a right-truncated discrete likelihood, in which the probability of a failure on day $\iota$ is $[F(\iota+1) - F(\iota)] / F(W+1)$, while the scale is not identifiable; early-failure rates of repaired or harvested parts relative to new ones are estimable when the number of parts installed is known. **[implemented]** `erc/fiabilite.py`; coverage of the 90 % interval for the shape is checked by simulation. The expected cost of an early failure is not yet a term of $\rho_{ij\mathsf R}$; it enters through the value $v_j$ supplied by the user. Making it explicit is an open item.

---

## 6. Irregular arrivals: what forecasting, buffering or reinforcement learning can gain

Scrapped units arrive irregularly. Let $A_k = (A_{ik})_i$ be the arrivals of period $k$, with $\mathbb{E} A_k$ finite and $\bar A = \lim_T \frac1T \sum_{k \le T} \mathbb{E} A_k$, and let $H$ hours be available in every period.

A **policy** chooses in each period, from the history, how many units of each type to process with each plan among the units on hand, within $H$ hours. Units not processed can be kept, within any storage limit, or released to the status quo. The **myopic** policy keeps no stock and solves (P) on each period's arrivals; it earns $V(A_k, H)$ in period $k$.

**Proposition 5 (fluid bound and variability gap) [proved].** Assume the initial stock is empty, the margins $g$ are known, and the limit $\bar A$ exists. For every policy, with $x_k$ the plan it applies in period $k$, the long-run average margin satisfies

$$\limsup_{T \to \infty} \frac1T\, \mathbb{E}\Big[\sum_{k=1}^{T} g^{\top} x_k\Big] \;\le\; V(\bar A, H),$$

and the myopic policy satisfies $\frac1T \sum_{k \le T} \mathbb{E}\, V(A_k, H) \le V\big(\frac1T \sum_{k\le T}\mathbb{E} A_k,\, H\big)$. Hence the gap

$$\Gamma \;=\; V(\bar A, H) \;-\; \liminf_{T}\frac1T \sum_{k \le T} \mathbb{E}\,V(A_k, H) \;\ge\; 0$$

is an upper bound on what *any* policy that stores units, forecasts arrivals or is trained by reinforcement learning can gain per period over the myopic policy. The same argument without expectations gives, for every realised sequence, $\sum_{k \le T} g^\top x_k \le T\, V\big(\tfrac1T \sum_{k \le T} A_k,\, H\big)$.

*Proof.* Fix $T$ and let $\bar x = \frac1T \sum_{k \le T} x_k$. With an empty initial stock, units processed by $T$ were received by $T$, so $\sum_s \bar x_{is} \le \frac1T \sum_{k \le T} A_{ik}$; each period uses at most $H$ hours, so $\sum_{i,s} h_{is} \bar x_{is} \le H$. This holds whatever the policy knows, including future arrivals. Completing $\bar x$ with the plan $s^0$, which costs no hours and earns nothing, gives a feasible point of (P) with data $(\frac1T \sum_{k \le T} A_k, H)$ and the same objective: this is the pathwise claim. Taking expectations and using the concavity of $V$ in $N$ (Proposition 2, Jensen) gives $\frac1T \mathbb{E}\sum_k g^\top x_k \le V(\bar A^T, H)$ with $\bar A^T = \frac1T\sum_{k\le T}\mathbb{E}A_k$, and the first claim follows by continuity of $V$, which is finite, concave and piecewise linear on $N \ge 0$. The claim on the myopic policy is Jensen's inequality for $N \mapsto V(N, H)$, applied to the empirical distribution over periods and to the expectation. $\blacksquare$

The argument is that of the deterministic upper bounds of revenue management (Gallego and van Ryzin 1994) and of the Jensen inequalities of stochastic linear programming (Madansky 1960).

**Consequences.**

1. The sample version of $\Gamma$, the annual model run on the average flow minus the model replayed week by week, is computable from the data. It is an exact hindsight bound for the observed history, and it estimates $\Gamma$ with a downward bias on short histories, since $\mathbb{E}\,V(\text{sample mean}, H) \le V(\text{mean}, H)$. **[implemented]** `erc/ligne.py::resultat_par_periode` reports it as *Coût de la variabilité du flux*.
2. It settles when sophisticated dynamic control is worth building. If $\Gamma$ is small relative to $V$, no buffer, forecast or learned policy can add much, and the myopic rule is enough. If it is large, the candidates are, in increasing order of complexity: a buffer with a base-stock rule; a rolling-horizon version of (P) fed with forecasts; a stochastic programme on forecast scenarios; a policy trained by reinforcement learning on a simulator. Each is assessed by the share of $\Gamma$ it recovers. Reinforcement learning is a candidate only for the residual that the simpler policies leave.
3. The bound is not tight in general: a finite buffer cannot smooth arbitrarily long droughts. The true optimum lies between the myopic value and $V(\bar A, H)$.
4. $\Gamma$ takes the margins as known. It does not bound the value of learning the yields, which Section 5 addresses.

**The dynamic model [not implemented].** With inventory $I_{ik}$ of units on hand, released units $o_{ik}$, a storage footprint $f_i$ and a storage limit $B$:

$$I_{i,k+1} = I_{ik} + A_{ik} - \sum_{s \ne s^0} x_{isk} - o_{ik}, \qquad \sum_i f_i I_{ik} \le B, \qquad \sum_{i,s} h_{is} x_{isk} \le H, \qquad x, o, I \ge 0 .$$

The state is the inventory together with the posterior on the yields. It is a Markov decision process whose exact solution is out of reach beyond small instances; the fluid bound is the benchmark against which approximate policies are measured.

---

## 7. Forecasting the arrivals

Weekly counts of scrapped units per type are short, low-count, intermittent series.

**Structural model.** A unit is scrapped when a unit received for repair is found beyond economic repair. With $E_{ik}$ the units of type $i$ that reached a decision in period $k$ (repaired plus scrapped) and $\sigma_i$ the scrap rate,

$$A_{ik} \mid E_{ik}, \sigma_i \sim \text{Binomial}(E_{ik}, \sigma_i), \qquad \sigma_i \sim \text{Beta}(\alpha_i, \beta_i).$$

The prior $(\alpha_i, \beta_i)$ of a type is estimated from the *other* types, by weighted moments from which the expected binomial sampling variance is removed, so that sparse types borrow strength and the data of a type are not used twice; with fewer than two other usable types the prior is the uninformative $\text{Beta}(\tfrac12, \tfrac12)$. The inflow $E_{ik}$ is a denser series, driven by the installed base, and is forecast separately; the predictive distribution of the next period's arrivals is Beta-binomial given a forecast of its inflow. The same construction applies in production, where $E$ is the planned output of a stage and $\sigma$ its nonconformity rate.

**References to beat.** The mean of the history; Croston's method (Croston 1972), its bias-corrected form (Syntetos and Boylan 2005) and the Teunter–Syntetos–Babai variant (2011), which are the standard methods for intermittent demand; a pooled Gamma–Poisson model with negative-binomial predictive distribution; and zero-shot time-series foundation models, which need no training on our data: Chronos (Ansari et al. 2024), TimesFM (Das et al. 2024), Moirai (Woo et al. 2024), Toto (Cohen et al. 2024, 2025) and Timestral (Mistral AI 2026). **[implemented]** for the statistical methods and the evaluation, `erc/prevision.py`; the foundation models are run through an adapter on a machine that holds their weights and are not part of the test suite. No foundation model has been run for this document.

**What "competing with foundation models" can mean here [to measure].** Foundation models are trained mostly on long, dense series; our series have a few dozen points and many zeros, and a known causal driver, the inflow $E$, that a univariate model does not see. The hypothesis to test is that the structural model matches or beats them on these series at a negligible computing cost. For the comparison to be on equal information, a model that accepts covariates (Timestral is described by its authors as supporting known-future covariates; any other listed model that does is treated the same way) is run twice: without $E$, and with $E$ supplied as a covariate. It is a hypothesis: public benchmarks contain some intermittent count series, but their aggregate rankings are dominated by other kinds of series and do not settle the question for series like ours.

**Evaluation protocol.** Rolling origin with expanding window; all methods are scored on the same forecasts, that is, on the (type, period) pairs that every compared method could forecast. Point accuracy by the root mean squared error relative to that of the historical mean; the absolute error is not used, because it is minimised by the median, which is zero as soon as more than half of the periods are empty. Probabilistic accuracy by the pinball loss on a grid of quantiles, which approximates the continuous ranked probability score, and by the coverage of the 80 % interval. These three are implemented. A fourth is planned and not yet coded: a decision-focused measure in the spirit of Elmachtoub and Grigas (2022), who treat predicted cost vectors. Here the forecast enters the right-hand side of (P), so the measure must name the decision that uses the forecast (for example the hours booked for the period) and the rule that makes the plan feasible on the realised arrivals; the loss is then $V(A_k, H)$ minus the margin of the plan so repaired. A forecast is only as good as the decision it supports.

---

## 8. Knowledge acquisition: what is worth knowing

### 8.1 The missing knowledge

The recycling price $p_j$, the applicable regulatory route and the content in critical raw materials all depend on the **material composition** of component $j$, which the bill of materials does not give: it lists a company part number and a free-text description. Composition can be obtained by several means of very different cost and reliability: a rule on the description; analogy with an already validated part; a manufacturer's material declaration (formats IEC 62474 and IPC-1752) or data sheet found on the web; an extraction by a language model from a retrieved document; a check of that extraction by a model; a human expert; a laboratory analysis.

### 8.2 A belief over composition, with sources of learned reliability

Let $C_j \in \bar{\mathcal{C}}$ be the unknown material class of component $j$, with a uniform prior $\pi_0$ on $\bar{\mathcal{C}}$. The value $\varnothing$ receives every class asserted outside the reference list, so that such a claim is neither lost nor mistaken for a listed class, and the number of possible values is the same for all components. A piece of evidence $\xi \in \Xi_j$ is a triple (source type $u_\xi$, class $c_\xi$, sign $\epsilon_\xi \in \{+1, -1\}$) of one of two kinds.

- An **assertion** names a class among all. A source of reliability $r$ names the true class with probability $r$ and otherwise one of the $|\bar{\mathcal{C}}| - 1$ others, uniformly.
- A **verdict** answers yes ($\epsilon_\xi = +1$) or no ($\epsilon_\xi = -1$) to the question "is it $c_\xi$?". A source of reliability $r$ answers correctly with probability $r$, whatever the true class. A denial is a verdict "no".

Pieces of evidence of the same source type share one unknown reliability $r_u \sim \text{Beta}(a_u, b_u)$; given the truth and the reliabilities, pieces of independent origin are independent. For a candidate class $c$, let $s_u(c)$ and $f_u(c)$ be the numbers of pieces of type $u$ that would be right and wrong if $C_j = c$, and $e_u(c)$ the number of wrong assertions among them. Integrating over the reliabilities,

$$P(C_j = c \mid \Xi_j) \;\propto\; \pi_0(c) \prod_{u} \frac{\mathrm{B}\big(a_u + s_u(c),\; b_u + f_u(c)\big)}{\mathrm{B}(a_u, b_u)}\; \big(|\bar{\mathcal{C}}| - 1\big)^{-e_u(c)},$$

where $\mathrm{B}$ is the Beta function. With one piece per source type the factor is the posterior mean $\bar r_u = a_u/(a_u + b_u)$ when the piece is right and $1 - \bar r_u$ when it is wrong; with several pieces of one type it is less confident than the product of means, because pieces that share an unknown reliability are not independent. **[implemented]** `erc/cortex.py::croyance`.

For assertions this is the observation model of Dawid and Skene (1979) restricted to one accuracy parameter per source with uniform errors, the "one-coin" model of the later crowdsourcing literature. Unlike Dawid and Skene, reliabilities are shared by source type and estimated from human-validated cases, not by the EM algorithm.

**Learning the reliabilities.** Each $r_u$ starts from a weak declared prior (a working assumption, equivalent to four observations). A human validation of a component shows which of its pieces of evidence were right. Validated components are not a random sample: those sent to review are the ones on which sources disagree, where at least one is wrong, and a naive count would make every source look bad. Each validation therefore carries its reason. Validations made without regard to what the sources say update the prior. Validations of components drawn at random among the accepted ones (audit), and validations of components the chain could not settle (queue), inform only their own stratum; the reliability used is the mean of the two strata, weighted by the number of pieces of that source type still to be judged in each. Validations of components picked by the reviewer set the class but do not judge the sources. The Beta update is unbiased only as far as the audit is random and the queue is reviewed in full. **[implemented]** `erc/cortex.py::fiabilites`.

Four consequences are deliberate.

- **A language model is a source, never ground truth.** Its readings and its verdicts enter the product with their own learned reliability. Ground truth is a human validation. A manufacturer's declaration is the most reliable source (declared prior 0.95), not ground truth.
- **Trust is earned.** With the declared priors, a document read by a model and checked by the same model does not reach the acceptance threshold; it does once validations have shown that this kind of reading is right often enough.
- **Independence is enforced by provenance, as far as it is traced.** Ten web pages that reproduce one data sheet are one piece of evidence: claims are counted once per source type and origin. A model that re-reads its own reading does not add a source: a "yes" turns the reading into a confirmed reading, a "no" withdraws it. A verdict by another model on the same document is treated as conditionally independent, which is an assumption. Two readers of the same text, a rule and a language model reading the same description, count as one piece of evidence when they agree, the more reliable of the two; when they disagree both count.
- **Unknown stays unknown.** A component whose class is not established has no bin, hence no price: in (P) it is in the state $\varnothing_j$ of Section 2, where sorting is unavailable. It is not valued at an average price.

### 8.3 Value of information

Two cases must be kept apart. For a parameter on which the decision maker can act at its mean (a yield, a value, the price of an established class known with error), the reference is the decision taken at the mean. For the class of a component, there is no "decision at the mean class": without a class the component cannot be sorted.

**Proposition 6 (value of information on a parameter, with a computable bound) [proved].** For fixed $(N, H)$, $V$ is a convex function of the vector of values $(\rho_{ijd})$, and therefore of every parameter that enters these values affinely: recycling prices, yields, reuse values. Let $\theta$ be such a parameter, uncertain with distribution $F$ and mean $\bar\theta$. The expected value of perfect information,

$$\text{EVPI} \;=\; \mathbb{E}_F\big[V(\theta)\big] - V(\bar\theta),$$

is nonnegative, and it is zero if and only if a solution that is optimal at $\bar\theta$ is optimal for $F$-almost every $\theta$. Moreover, if the slopes of $V$ in $\theta$ lie in an interval of length $\Delta$, then $\text{EVPI} \le \tfrac12\, \Delta\; \mathbb{E}_F|\theta - \bar\theta|$, and the constant $\tfrac12$ cannot be improved. In particular, for the price $p_j$ of component $j$,

$$\text{EVPI} \;\le\; \tfrac12\, N^{c}_j\, m_j \;\mathbb{E}_F\big|p_j - \bar p_j\big| ,$$

and for the yield $q_{ij}$, $\ \text{EVPI} \le \tfrac12\, N_i\, n_{ij}\, |\lambda_{ij}|\; \mathbb{E}_F|q_{ij} - \bar q_{ij}|$, where $\lambda_{ij}$ is the coefficient of $q_{ij}$ in $\rho_{ij\mathsf R}$: $\bar v_j - m_j p_j$ with complete data, $\bar v_j + \tau m_j$ when $p_j$ is unknown, $\bar v_j$ when $m_j$ is unknown.

*Proof.* For a fixed feasible $x$ the objective $g(\theta)^\top x$ is affine in $\theta$, and $V$ is the pointwise maximum of these affine functions over a feasible set that does not depend on $\theta$, hence convex. Let $x^\ast$ be optimal at $\bar\theta$. Then $V(\bar\theta) = g(\bar\theta)^\top x^\ast = \mathbb{E}_F[g(\theta)^\top x^\ast] \le \mathbb{E}_F[V(\theta)]$, with equality if and only if $g(\theta)^\top x^\ast = V(\theta)$ almost surely. For the bound, let the slopes of $V$ lie in $[\underline\lambda, \overline\lambda]$ with $\overline\lambda - \underline\lambda = \Delta$, and put $\lambda^\circ = (\underline\lambda + \overline\lambda)/2$. The function $U(\theta) = V(\theta) - \lambda^\circ \theta$ is convex with slopes in $[-\Delta/2, \Delta/2]$, hence $|U(\theta) - U(\bar\theta)| \le \tfrac12 \Delta |\theta - \bar\theta|$; and $\mathbb{E}_F[V(\theta)] - V(\bar\theta) = \mathbb{E}_F[U(\theta) - U(\bar\theta)]$ because $\mathbb{E}_F[\theta - \bar\theta] = 0$. The constant is attained by $V(\theta) = \Delta\,(\theta - \bar\theta)^+$. For a price, the slope of the margin of any feasible $x$ is $m_j$ times the number of copies of $j$ sold by the kilogram, which lies in $[0, N^{c}_j m_j]$ since $j$ may belong to several types. For a yield, it is $\lambda_{ij}$ times the number of copies of $j$ reused in type $i$, which lies between $0$ and $N_i n_{ij} \lambda_{ij}$. $\blacksquare$

The value without information is $V(\bar\theta)$ because the decision maker is risk-neutral and the margin is affine in $\theta$; for yields, the realised margin depends on realised good counts whose expectation is $q$.

**Proposition 7 (value of establishing a class) [proved].** In the instance of Section 2, let the class of component $j$ be unknown, with belief $P(C_j = c)$ and price $p(c)$ for class $c$. Let $V(\varnothing_j)$ be the value of (P) when $j$ has no price, and $V(p)$ its value when the price of $j$ is $p$. Then

$$\mathbb{E}\big[V(p(C_j))\big] - V(\varnothing_j) \;\le\; N^{c}_j\, m_j\; \mathbb{E}\big[(p(C_j) + \tau)^+\big],$$

and the left-hand side is nonnegative when $p(c) + \tau \ge 0$ for every class of positive probability. For the value $\varnothing$ (a class outside the reference list) there is no sorted outlet: the component stays unsortable and contributes zero to both sides.

*Proof.* Fix a price $p$ and let $x$ be optimal for it. Replace, in every plan, the disposition $\mathsf S$ of $j$ by $0$. The access level of a plan does not rise: it stays 2 if another component is reused, stays 1 if another is sorted, and otherwise falls to 0, where the opening time is zero. Hours do not increase, so the new solution is feasible for the problem without a price. Per unit of type $i$, a plan that sorted $j$ loses $n_{ij} m_j (p + \tau)$ minus the labour saved; a plan that reused $j$ loses $n_{ij}(1 - q_{ij}) m_j (p + \tau)$, the difference between the two expressions of $\rho_{ij\mathsf R}$ in Section 2; other plans lose nothing. Each loss is at most $n_{ij} m_j (p + \tau)^+$, and at most $N_i$ units of type $i$ are processed, so $V(p) - V(\varnothing_j) \le N^{c}_j m_j (p+\tau)^+$; take the expectation over the class. Conversely, when $p + \tau \ge 0$ every plan is worth at least as much with the price as without, so $V(p) \ge V(\varnothing_j)$. $\blacksquare$

The left-hand side can be negative when a possible class costs more to recycle than the bulk stream: establishing the class then reveals an obligation, not an opportunity, and the decision to establish it is not an economic one.

**Use.** The quantities above are per period, while a composition is acquired once and stays valid; the comparison is made over the periods during which the answer stays valid (one year in the implementation).

1. *Screen (Proposition 7).* An acquisition about the class of $j$ is made only if the bound, computed under the current belief, covers what has already been spent on $j$ plus the cost of the acquisition. Acquisitions are tried from the cheapest: free evidence (rule, analogy, earlier classification), a reading of the internal description by the privately hosted model, document retrieval, reading of a document by a model, verdict by a model, the last only when a "yes" would be enough for acceptance. Light or rare components stop at the free evidence without any model call.
2. *Acceptance.* A class $\hat c$ is accepted without review when its probability reaches a threshold and the value at risk, $\big(1 - P(C_j = \hat c)\big)\, N^{c}_j m_j \max_c (p(c) + \tau)^+$ over the plausible classes, is below the cost of a review. Accepted classes are audited by random sampling, which is also what measures the reliabilities without bias.
3. *Review.* The other components go to a human, ranked by the bound; for those that belong to the line model, the exact value $\mathbb{E}[V(p(C_j))] - V(\varnothing_j)$ is computed by solving (P) under each class.

**[implemented]** `erc/composition.py` for the screen with its budget, the acceptance rule and the queue; `erc/information.py` for the bounds of Propositions 6 and 7 and the exact values by scenarios; `erc/composition_outil.py` for the review page, with its audit sample. Ranking the automatic acquisitions by exact value per unit cost is **[not implemented]**: the chain follows a fixed cheapest-first order. The mass used by the screen is the annual mass of the component in the streams the decision covers: the defective copies replaced in repairs, plus the copies contained in the scrapped units of the line model. Information value theory goes back to Howard (1966); the value of yield information in remanufacturing is studied by Ferrer and Ketzenberg (2004). What is specific here is that the value is computed through the operational model that will use the answer, so that characterisation effort goes to the components whose composition can change a decision.

### 8.4 Confidentiality constraint

A company part number and the description of an in-house design are not public. The acquisition layer therefore never sends them outside. An outward query contains only a manufacturer's name, a manufacturer's part number and a generic component type, and it is issued only if: the component is not flagged as designed in-house (any unrecognised value of the flag counts as in-house); a manufacturer is named and is not the company itself; and the part number has the form of a manufacturer's reference and is not the company part number of any component of the bill of materials. The language model is self-hosted: it runs on the local machine or on a machine of the owner's network that the owner has declared. Only such a private model may read internal descriptions, which makes it the one automatic source for in-house designs; any other server is refused unless explicitly accepted, and then receives public documents only. Outward queries are built from bill-of-materials fields before any model call, so that nothing a model answers, including under the influence of a hostile document, can enter a request. **[implemented]** as a policy of `erc/composition.py`; tests check that no internal identifier or description appears in an outgoing request in each of these cases. The guarantee assumes that the manufacturer-reference column of the bill of materials contains manufacturer references; this must be checked on the data before a retrieval service is connected.

---

## 9. Circularity and access as objectives

Three outcomes are linear in $x$ and are reported for every solution: the mass diverted from the bulk stream, $\sum_{i,s} b_{is} x_{is}$, with $b_{is}$ the mass taken out of a unit under plan $s$; the mass of critical or strategic raw materials directed to a recovery route; and the number of parts returned to service, $\sum_{i,s} e_{is} x_{is}$ with $e_{is} = \sum_{j : s_j = \mathsf R} n_{ij} q_{ij}$.

Because they are linear, the trade-off between margin and any of them is traced exactly by adding a weighted term to the objective or a lower bound as a constraint. A weighted term adds no constraint and keeps at most one split type. With $M$ lower bounds there are $M + 1$ coupling constraints, the labour budget and the $M$ outcome constraints, so by Proposition 3 at most $M + 1$ types are split whenever the programme is feasible; a lower bound set too high makes it infeasible. The frontier answers a question that a single-objective optimum cannot: *how much margin does each additional part returned to service cost?* **[proved]** as a corollary of Proposition 3; **[not implemented]**.

Returning parts to service lowers the cost of repair and of refurbished systems. Whether and how much this improves access to equipment for hospitals with small budgets is an empirical question outside the model: the framework supplies the count of parts and its cost, and makes no claim about prices or access. **[to measure]**

---

## 10. From the repair centre to production

| Abstract object | Repair centre | Production (for example X-ray tube manufacturing) |
|---|---|---|
| unit type $i$ | type of scrapped FRU | nonconforming assembly at a given stage |
| arrivals $A_{ik}$ | scrapped FRUs per week | nonconformities: output of the stage times its defect rate |
| inflow $E_{ik}$ | units reaching a repair decision | units produced at the stage |
| component $j$ | part of the FRU | sub-assembly or material fraction |
| dispositions $\mathcal{D}$ | reuse in repair, sorted recycling, leave | rework, harvest for a new build, sorted recycling, scrap as is |
| access levels | rough or careful opening | disassembly depth; may be irreversible |
| yield $q_{ij}$ | share of extracted parts that pass test | share of harvested sub-assemblies that requalify |
| resource $H$ | operator hours outside the workload | rework stations, test benches |
| composition $C_j$ | drives recycler price and waste route | drives recovery route and handling rules for regulated materials |
| fixed cost $K$ | teardown and test line | rework cell |

What changes in production, and how the framework absorbs it:

- **More dispositions and deeper bills of materials.** The model is written for any finite $\mathcal{D}$ and $\mathcal{L}$; Proposition 1 keeps the pricing problem linear in the number of components, so the number of components per unit is no longer a limit. The current code fixes three dispositions and two opening levels; generalising them is a change of data structures, not of mathematics.
- **Mandatory routes.** A component whose class requires a licensed route has a restricted disposition set $\mathcal{D}_j(C_j) \subseteq \mathcal{D}$; this removes plans and leaves (P) unchanged in form. It is one more reason to know the composition before deciding.
- **Value added along the stages.** A unit scrapped late carries more value; types are indexed by stage.
- **Several coupling resources.** With $M$ resources Proposition 3 gives at most $M$ split types, and the dual has one price per resource.
- **The knowledge base is domain-neutral.** The store of claims, validations and learned reliabilities of Section 8.2 takes any domain, subject and attribute; only the acquisition chain is specific to composition.

None of this is implemented or validated on production data. **[to measure]**

---

## 11. What a journal submission requires

**Venue.** The *INFORMS Journal on Applied Analytics* publishes accounts of analytics in practice. Its submission guidelines require a verification letter for *use cases*, that is, full-length articles that are neither literature reviews nor tutorials; the letter is written by someone who is not an author, and the paper is not sent out for review without it. The journal's calls for papers ask for a signed letter on company letterhead addressed to the editor-in-chief, and its reviewer guidelines for a letter from the client organisation confirming that the work is in use and verifying the benefits accrued. We infer that a study on fictional data cannot be submitted there as a use case. These statements were read in November 2026 through search-engine extracts of the journal's pages, which could not be opened from the working environment; each clause must be re-read on the page itself before a submission is planned around it.

Without an implemented application, the options are the following. In the same journal, a tutorial or a literature review, which are exempt from the letter. For the disposition model and its structure (Sections 3 to 6), *Manufacturing & Service Operations Management*, or one of the journals where the disassembly and recovery-strategy literature appeared (*International Journal of Production Research*, *Omega*, *OR Spectrum*, *IISE Transactions*, *Production and Operations Management*). For the value-of-information layer (Section 8) as a separate paper, *Decision Analysis*. For the algorithm and its open implementation, *INFORMS Journal on Computing*. A practice summary of two to four pages in the *Journal on Applied Analytics* describes work done for a client and becomes possible only after the pilot. The scope statements of these journals were not all checked.

**Before any submission, to be established with field data [to measure]:**

1. The input flow is verified: estimated against weighed mass within the stated margin, over at least a quarter.
2. Teardown audits give times per type and per component and at least a few hundred tested copies; the prequential scores of Section 5.3 are reported.
3. Recycler quotations exist for the sorted streams; compositions of the components that matter (by EVPI) are validated by a human or a manufacturer's declaration.
4. A pilot runs on one or two types for long enough to compare realised and predicted margin, with the finance function validating the valuation of reused parts.
5. The counterfactual is stated: what the bulk contract cost over the same period.
6. Forecasting methods are compared on the actual series with the protocol of Section 7.

**Contributions that the framework supports, stated at their current strength.**

- **What is not new.** The model class is known. (P) is the linear multiple-choice knapsack problem (Sinha and Zoltners 1979; Zemel 1980), and Proposition 3 with a single budget is its classical solution structure. Choosing a disassembly depth and a recovery option per sub-assembly is the recovery-strategy problem of Krikke et al. (1998) and Teunter (2006); the multi-product programme with one variable per product and configuration is in Meacham et al. (1999). Propositions 2, 5 and 6 apply standard arguments: linear-programming duality; the deterministic upper bound used in revenue management (Gallego and van Ryzin 1994); and the Jensen inequalities of stochastic linear programming (Madansky 1960).
- **What the document adds.** The pricing of a unit by nested access level under a single labour price, which removes the enumeration of plans (Proposition 1); the yield threshold as a function of that price, a rule applicable at the bench (Proposition 4); the reading of the variability gap as a certificate, computable from data, of how much buffering, forecasting or reinforcement learning can add (Proposition 5), which turns "should we use reinforcement learning?" into a number; the value of establishing the class of a component, with its bound (Proposition 7); and the coupling of the operational model with posterior sampling on yields and with a value-of-information screen that limits the web lookups and language-model calls to those the stake of a component can pay for (Propositions 6 and 7), fed by a knowledge base whose sources have learned reliabilities.
- **Confidence in the novelty.** We have not found these elements in the papers of Section 1. This rests on their abstracts and on about ten targeted searches, none of which returned a multiple-choice knapsack or bandit formulation for product recovery. It is absence of evidence only, and must be confirmed on the full texts and by a systematic search before any claim is made in a submission.
- An open implementation with tests, including agreement with an exact solver.

---

## 12. Map to the implementation

| Section | Module | Checked by |
|---|---|---|
| 2–4 values, (P), multiplier, structure | `erc/ligne.py` | `tests/test_ligne.py`: exact LP solver on 600 instances, hand-computed cases, unknown-value matrix |
| 4.1 pricing without enumeration | `erc/ligne.py`, class `Options` | `tests/test_ligne.py`: agreement with enumeration; exact solver on types of 9 and 10 components |
| 4 browser recomputation of (P) | `erc/outil_modele.js` | `tests/test_outil.py`: agreement with the Python model on random scenarios, including large types |
| 5 prior, posterior, TS-LP, scores | `erc/rex.py`, `erc/parametres.py` | `tests/test_stats.py` |
| 5.4 early failures, Weibull shape | `erc/fiabilite.py` | `tests/test_stats.py`: coverage by simulation |
| 6 week-by-week replay, variability gap | `erc/ligne.py::resultat_par_periode` | `tests/test_ligne.py`, `tests/test_information.py` |
| 7 forecasting and its evaluation | `erc/prevision.py` | `tests/test_prevision.py`: recursions by hand, no leakage, common scoring set, priors across types |
| 8.2 belief, source reliability by strata | `erc/cortex.py` | `tests/test_composition.py`: fusion formulas, verdict channel, strata, schema of earlier files |
| 8.3 acquisition chain, budget, acceptance | `erc/composition.py` | `tests/test_composition.py`: minimum of calls, no repeated payment, failures, order independence |
| 8.3 bounds and exact values | `erc/information.py` | `tests/test_information.py`: Propositions 2 to 7 on random instances, tight case of the bound |
| 8.3 human review and audit sample | `erc/composition_outil.py`, `erc/composition_gabarit.html` | `tests/test_composition_outil.py`: decisions exported by the page return to the knowledge base |
| 8.4 confidentiality | `erc/composition.py::requete_publique`, `erc/modele.py` | `tests/test_composition.py`, `tests/test_modele.py`: internal codes, free text, own company, in-house flag, descriptions sent to a private model only, model output never in a request |
| input flow verified against weighing | `erc/flux.py` | `tests/test_stats.py` |

---

## 13. Limits and open problems

1. **No field result.** All numbers in the repository are produced from fictional data. The mathematics is independent of them; every managerial claim is not.
2. **Three dispositions, two opening levels.** The code implements the instance of Section 2. Proposition 1 holds for any finite sets, but the general pricing routine is not coded.
3. **Independence (A3)** is doubtful: a unit scrapped for one cause often has correlated damage. A model with unit-level condition classes would relax it, in the spirit of quality grading (Ferguson et al. 2009), at the price of more parameters to learn.
4. **Regret guarantees** for TS-LP are not claimed. The problem is a combinatorial semi-bandit, for which bounds exist for Thompson sampling (Wang and Chen 2018); whether their assumptions cover our instance has not been checked.
5. **Demand for reused parts** is assumed to absorb the supply. A cap on the copies of $j$ returned to service adds one constraint per saturated component and, by Proposition 3, one possible split type each.
6. **Source independence** in Section 8.2 holds only as far as provenance is traced. Reliabilities are per source type, not per site. Two source types can share a cause of error: a rule on the description and an earlier classification made with similar rules count as two sources and should not; a verdict on a document and the reading of the same document are treated as conditionally independent.
7. **Reliability by strata** is unbiased only if the audit sample is random and the review queue is reviewed in full; a queue reviewed from the top down is not a random sample of the queue.
8. **Acceptance** rests on a probability threshold and on a value at risk that ignores the cost of contaminating a sorted stream with a misclassified part. A recycler's penalty for contamination would enter as a larger value at risk.
9. **Composition as a single class** is a simplification; mass fractions over several materials call for a Dirichlet belief and a price that is a weighted sum, which keeps Proposition 6 unchanged since the price remains affine in the fractions.
10. **Risk neutrality.** A decision maker who must not lose money on the line would use a chance constraint or a conditional value-at-risk on the Monte-Carlo distribution that the package already produces.
11. **Text matching** for analogy is a bag of words. It is transparent and cheap, and weak on short or coded descriptions; an embedding model run locally would be a further source type, with its own learned reliability.

---

## References

Status: **V** = bibliographic details matched, during the preparation of this document, against a publisher, repository or index record returned by web search (the pages of some publishers could not be opened from the working environment, so the match is with the record, not with the article itself); **C** = cited from memory, to be checked before submission. What a paper is said to contain rests on its abstract unless stated otherwise.

- Ansari, A. F., et al. (2024). Chronos: Learning the language of time series. *Transactions on Machine Learning Research*, October 2024. arXiv:2403.07815. **V** (author list to be written out)
- Badanidiyuru, A., Kleinberg, R., Slivkins, A. (2018). Bandits with knapsacks. *Journal of the ACM* 65(3), 1–55. **V** (article number to add)
- Cohen, B., Khwaja, E., Wang, K., Masson, C., Ramé, E., Doubli, Y., Abou-Amal, O. (2024). Toto: Time series optimized transformer for observability. arXiv:2407.07874. **V**
- Cohen, B., et al. (2025). This time is different: An observability perspective on time series foundation models. arXiv:2505.14766. **V** (author list to be written out; a proceedings version, if any, should replace the preprint)
- Croston, J. D. (1972). Forecasting and stock control for intermittent demands. *Operational Research Quarterly* 23(3), 289–303. **C** (author, title, year and first page matched)
- Das, A., Kong, W., Sen, R., Zhou, Y. (2024). A decoder-only foundation model for time-series forecasting. *Proceedings of the 41st International Conference on Machine Learning*, PMLR 235:10148–10167. **V**
- Dawid, A. P., Skene, A. M. (1979). Maximum likelihood estimation of observer error-rates using the EM algorithm. *Applied Statistics* 28(1), 20–28. **V**
- Elmachtoub, A. N., Grigas, P. (2022). Smart "predict, then optimize". *Management Science* 68(1), 9–26. **V**
- Everett, H. (1963). Generalized Lagrange multiplier method for solving problems of optimum allocation of resources. *Operations Research* 11(3), 399–417. **V**
- Ferguson, M. E., Fleischmann, M., Souza, G. C. (2011). A profit-maximizing approach to disposition decisions for product returns. *Decision Sciences* 42(3), 773–798. **V**
- Ferguson, M., Guide, V. D. R., Koca, E., Souza, G. C. (2009). The value of quality grading in remanufacturing. *Production and Operations Management* 18(3), 300–314. **V**
- Ferreira, K. J., Simchi-Levi, D., Wang, H. (2018). Online network revenue management using Thompson sampling. *Operations Research* 66(6), 1586–1602. **V**
- Ferrer, G., Ketzenberg, M. E. (2004). Value of information in remanufacturing complex products. *IIE Transactions* 36(3), 265–277. **V**
- Fleischmann, M., Bloemhof-Ruwaard, J. M., Dekker, R., van der Laan, E., van Nunen, J. A. E. E., Van Wassenhove, L. N. (1997). Quantitative models for reverse logistics: A review. *European Journal of Operational Research* 103(1), 1–17. **V**
- Fleischmann, M., van Nunen, J. A. E. E., Gräve, B. (2003). Integrating closed-loop supply chains and spare-parts management at IBM. *Interfaces* 33(6), 44–56. **V**
- Frazier, P. I., Powell, W. B., Dayanik, S. (2008). A knowledge-gradient policy for sequential information collection. *SIAM Journal on Control and Optimization* 47(5), 2410–2439. **V**
- Gallego, G., van Ryzin, G. (1994). Optimal dynamic pricing of inventories with stochastic demand over finite horizons. *Management Science* 40(8), 999–1020. **C**
- Guide, V. D. R., Van Wassenhove, L. N. (2009). OR Forum: The evolution of closed-loop supply chain research. *Operations Research* 57(1), 10–18. **V**
- Howard, R. A. (1966). Information value theory. *IEEE Transactions on Systems Science and Cybernetics* 2(1), 22–26. **C** (first page matched; one index gives a different last page)
- Inderfurth, K., Langella, I. M. (2006). Heuristics for solving disassemble-to-order problems with stochastic yields. *OR Spectrum* 28(1), 73–99. **V**
- Ketzenberg, M. E., van der Laan, E., Teunter, R. H. (2006). Value of information in closed loop supply chains. *Production and Operations Management* 15(3), 393–406. **V**
- Krikke, H. R., van Harten, A., Schuur, P. C. (1998). On a medium term product recovery and disposal strategy for durable assembly products. *International Journal of Production Research* 36(1), 111–139. **V** (some records give 111–140)
- Madansky, A. (1960). Inequalities for stochastic linear programming problems. *Management Science* 6(2), 197–204. **C**
- Meacham, A., Uzsoy, R., Venkatadri, U. (1999). Optimal disassembly configurations for single and multiple products. *Journal of Manufacturing Systems* 18(5), 311–322. **C** (authors, title, year and DOI 10.1016/S0278-6125(00)87634-7 matched; volume and pages from memory)
- Mistral AI (2026). Timestral. arXiv:2610.37585; announcement of 15 October 2026, mistral.ai/news/timestral. **V** (existence, title and identifier; the author list of the preprint is to be written out; benchmark claims are the publisher's)
- Reveliotis, S. A. (2007). Uncertainty management in optimal disassembly planning through learning-based strategies. *IIE Transactions* 39(6), 645–658. **V**
- Russo, D., Van Roy, B. (2014). Learning to optimize via posterior sampling. *Mathematics of Operations Research* 39(4), 1221–1243. **V**
- Sinha, P., Zoltners, A. A. (1979). The multiple-choice knapsack problem. *Operations Research* 27(3), 503–515. **V**
- Syntetos, A. A., Boylan, J. E. (2005). The accuracy of intermittent demand estimates. *International Journal of Forecasting* 21(2), 303–314. **V**
- Teunter, R. H. (2006). Determining optimal disassembly and recovery strategies. *Omega* 34(6), 533–537. **V**
- Teunter, R. H., Syntetos, A. A., Babai, M. Z. (2011). Intermittent demand: Linking forecasting to inventory obsolescence. *European Journal of Operational Research* 214(3), 606–615. **V**
- Thierry, M., Salomon, M., van Nunen, J., Van Wassenhove, L. (1995). Strategic issues in product recovery management. *California Management Review* 37(2), 114–135. **V**
- Wang, S., Chen, W. (2018). Thompson sampling for combinatorial semi-bandits. *Proceedings of the 35th International Conference on Machine Learning*, PMLR 80:5114–5122. **V**
- Woo, G., Liu, C., Kumar, A., Xiong, C., Savarese, S., Sahoo, D. (2024). Unified training of universal time series forecasting transformers. *Proceedings of the 41st International Conference on Machine Learning*, PMLR 235:53140–53164. **V**
- Zemel, E. (1980). The linear multiple choice knapsack problem. *Operations Research* 28(6), 1412–1423. **C**
- INFORMS Journal on Applied Analytics: submission guidelines (pubsonline.informs.org/page/ijaa/submission-guidelines), calls for papers and reviewer guidelines. Read in November 2026 through search-engine extracts, not on the pages. **C**
- IEC 62474:2018 with Amendment 1:2020, *Material declaration for products of and for the electrotechnical industry*; IPC-1752B, *Materials declaration management standard* (the current revision is to be checked). **C**
