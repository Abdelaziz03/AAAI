# From scrap to value: knowledge, learning and optimisation for the disposition of scrapped units

*Formal framework of the project. Working document for a journal submission; written in English because the target venues are. The team-facing French description of the line model is `Modele_mathematique.md`.*

**How to read the status marks.** Every statement carries one of four marks.

| Mark | Meaning |
|---|---|
| **[proved]** | A proof is given here. The result is also checked numerically where a test is named. |
| **[implemented]** | Coded in the package and covered by tests; the module is named. |
| **[literature]** | Established elsewhere; the reference is given. We do not re-prove it and do not claim it transfers to our setting unless stated. |
| **[to measure]** | A claim that needs field data. Nothing in this document is an empirical result: every number in the repository comes from fictional demonstration data. |

---

## 1. Problem and scope

A repair centre for medical equipment receives field-replaceable units (FRUs). Some are repaired; the others are **scrapped** and today leave whole through a bulk waste contract that produces no revenue. Each scrapped unit still contains components that could be (i) **reused** in repairs after extraction and test, (ii) **repaired or remanufactured**, (iii) **sorted** and sold by the kilogram to a specialised recycler, or (iv) left in the unit (status quo). Extraction takes operator time that is not in the current workload, opening a unit is a set-up paid once per unit, the share of components that are still good is unknown, the flow of scrapped units is irregular, and the material composition of most components, which determines recycling prices and regulatory routes, is not recorded anywhere.

The decision problem has three layers:

1. **Disposition.** For each type of scrapped unit, whether to open it, and what to do with each component, under a labour budget (Sections 3 and 4).
2. **Learning and forecasting.** Estimating the yields that drive the reuse value, and the arrivals that drive the workload, while decisions are being taken (Sections 5 to 7).
3. **Knowledge acquisition.** Deciding which missing facts (compositions, yields) are worth acquiring, and by which means, given what each costs (Section 8).

The same structure appears in **production**: a nonconforming assembly at a production stage is a scrapped unit; its sub-assemblies can be reworked, harvested for new builds, or sorted by material. Section 10 gives the correspondence. The model is therefore written for abstract *unit types*, *components*, *dispositions*, *access levels* and *resources*, and an application is a data instance.

**Why it matters beyond cost [to measure].** Reused and repaired parts lower the cost of keeping imaging systems running and of refurbishing them, which is one of the levers for access to imaging in hospitals with small budgets; sorted streams keep critical raw materials in use. Section 9 states these outcomes as measurable quantities. The framework makes no claim about their size.

---

## 2. Notation

**Sets.**

| Symbol | Meaning |
|---|---|
| $\mathcal{I}$ | types of scrapped unit |
| $\mathcal{J}_i$ | components of a unit of type $i$ |
| $\mathcal{D}$ | dispositions of a component; $0 \in \mathcal{D}$ is "leave in the unit" |
| $\mathcal{L} = \{0, 1, \dots, L\}$ | access levels of a unit, ordered; $0$ = not opened |
| $\mathcal{S}_i = \mathcal{D}^{\mathcal{J}_i}$ | plans for a unit of type $i$: one disposition per component; $s^0$ = all components left |
| $\mathcal{T}$ | periods |
| $\mathcal{C}$ | material classes |

**Data of the static problem** (one period; the period index is dropped).

| Symbol | Meaning |
|---|---|
| $N_i \ge 0$ | scrapped units of type $i$ available |
| $n_{ij} \ge 1$ | copies of component $j$ in a unit of type $i$ |
| $\ell_d \in \mathcal{L}$ | access level that disposition $d$ requires; $\ell_0 = 0$ |
| $a_{i\ell} \ge 0$ | time to open a unit of type $i$ to level $\ell$; $a_{i0} = 0$ |
| $t_{jd} \ge 0$ | operator time per copy of $j$ under disposition $d$; $t_{j0} = 0$ |
| $\rho_{ijd}$ | net value per copy of $j$ under $d$, before labour; $\rho_{ij0} = 0$ |
| $w_i \ge 0$ | cost of an operator hour on type $i$ |
| $H \ge 0$ | operator hours available |
| $K \ge 0$ | fixed cost of the line for the period (amortised investment plus fixed costs) |

For a plan $s \in \mathcal{S}_i$, the induced access level, the hours and the margin per unit are

$$\ell(s) = \max_{j \in \mathcal{J}_i} \ell_{s_j}, \qquad h_{is} = a_{i\,\ell(s)} + \sum_{j} n_{ij}\, t_{j s_j}, \qquad g_{is} = \sum_{j} n_{ij}\, \rho_{i j s_j} - w_i\, h_{is}.$$

The plan $s^0$ has $h_{i s^0} = 0$ and $g_{i s^0} = 0$: the status quo is the reference and is worth zero.

**The instance used in the repair centre.** Three dispositions: reuse ($\mathsf{R}$, level 2), sorted recycling ($\mathsf{S}$, level 1), leave ($0$). With $q_{ij}$ the probability that an extracted copy is reusable, $v_j$ the value of a reused copy, $L_j \lambda_j$ the value of the procurement lead time it avoids, $\kappa_j$ transport, $m_j$ its mass, $p_j$ the price paid by the recycler, and $\tau$ the cost per kilogram of the current bulk treatment (negative if the current contractor pays):

$$\rho_{ij\mathsf{R}} = q_{ij}\,(v_j + L_j\lambda_j) + (1 - q_{ij})\, m_j p_j + \tau m_j - \kappa_j, \qquad \rho_{ij\mathsf{S}} = m_j\,(p_j + \tau),$$

$$t_{j\mathsf{R}} = t^{\text{ext}}_j + t^{\text{test}}_j, \qquad t_{j\mathsf{S}} = t^{\text{sort}}_j .$$

A copy that fails its test is sold by the kilogram; every copy taken out of the unit avoids the bulk treatment. When $m_j$ or $p_j$ is unknown the implementation drops the corresponding terms and reports them (column *Non compté faute de donnée*); it never replaces an unknown by zero silently. **[implemented]** `erc/ligne.py`, `valeurs_options`.

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

(P) is the linear relaxation of a multiple-choice knapsack problem (Sinha and Zoltners 1979): each type is a class, each plan an item, the labour budget the knapsack. The relaxation is the natural model here because $N_i$ counts many identical units; Remark 1 bounds what integrality costs. (P) is always feasible ($x_{i s^0} = N_i$) and bounded.

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

*Status of the implementation.* The code enumerates plans, which is exact without A1, and for that reason examines at most eight components per type; a type with more is solved on its eight most valuable components and the plan names the others (*Pièces non examinées*), so the reported value is then a lower bound. Replacing the enumeration by Proposition 1 removes the limit and is the planned next step for production instances.

**Proposition 2 (dual and value function) [proved].**

$$V(N, H) \;=\; \min_{\mu \ge 0} \Big\{ \mu H + \sum_{i \in \mathcal{I}} N_i\, \varphi_i(\mu) \Big\}.$$

$V$ is concave, piecewise linear and positively homogeneous of degree one in $(N, H)$, and nondecreasing in each argument. If $\mu^\ast$ attains the minimum, then $V(N, H') \le V(N, H) + \mu^\ast (H' - H)$ for every $H' \ge 0$: $\mu^\ast$ is the net value of one more operator hour, and it is zero when the labour budget is not exhausted.

*Proof.* Dualise the capacity constraint with multiplier $\mu \ge 0$; the remaining problem separates by type and its value is $N_i \varphi_i(\mu)$ since all of $N_i$ goes to a best plan. Strong duality holds because (P) is a feasible bounded linear programme. The optimal value of a maximisation linear programme is concave and piecewise linear in its right-hand side, and positive homogeneity follows from scaling $x$. Monotonicity in $H$ is the relaxation of a constraint; monotonicity in $N_i$ holds because additional units can be assigned $s^0$ at no cost. The inequality is the supergradient property of the dual solution: for any $H'$, weak duality gives $V(N, H') \le \mu^\ast H' + \sum_i N_i \varphi_i(\mu^\ast) = V(N, H) + \mu^\ast(H' - H)$. $\blacksquare$

The dual objective is convex and piecewise linear in $\mu$, with subgradient $H - \sum_i N_i h_{i s_i(\mu)}$ at any selection $s_i(\mu)$ of best plans. The implementation locates $\mu^\ast$ by bisection on the sign of this subgradient (Everett 1963), then recovers a primal solution by Proposition 3. **[implemented]** `erc/ligne.py`, `optimiser_ligne`; the optimal value equals that of an exact LP solver (HiGHS) within $10^{-6}$ on 600 random instances, and the multiplier is bracketed by the left and right finite-difference slopes of $V$ (`tests/test_ligne.py`).

### 4.2 Shape of an optimal solution

**Proposition 3 (few split types, efficient plans) [proved].** (P) has an optimal solution in which every type uses one plan, except at most one type, which uses two. In any optimal solution, with $\mu^\ast$ an optimal multiplier, every plan in use attains $\varphi_i(\mu^\ast)$; in particular it lies on the upper concave envelope of the points $\{(h_{is}, g_{is})\}_{s \in \mathcal{S}_i}$, and the two plans of a split type lie on a common edge of that envelope, of slope $\mu^\ast$. More generally, with $R$ coupling constraints in place of the single labour budget, there is an optimal solution in which at most $R$ types use more than one plan.

*Proof.* Add a slack to each coupling constraint. The programme has $|\mathcal{I}| + R$ equality constraints, so an optimal basic solution, which exists because the programme is feasible and bounded, has at most $|\mathcal{I}| + R$ positive variables. Each type with $N_i > 0$ needs at least one positive plan variable, which leaves at most $R$ further positive variables, hence at most $R$ types with a second plan (types with $N_i = 0$ use none). For the second claim let $(\pi, \mu^\ast)$ be optimal dual variables: dual feasibility reads $\pi_i \ge g_{is} - \mu^\ast h_{is}$ for all $s$, and complementary slackness gives equality whenever $x_{is} > 0$. So a plan in use maximises $g_{is} - \mu^\ast h_{is}$ over $\mathcal{S}_i$, that is, the line of slope $\mu^\ast$ through $(h_{is}, g_{is})$ supports the point set from above. Two plans of the same type in use lie on the same supporting line. $\blacksquare$

**Remark 1 (integrality).** Rounding the split type down to whole units and sending the remainder to the cheaper of its two plans keeps the solution feasible and loses less than the margin difference of one unit. With hundreds of units per type the relaxation is immaterial.

**Managerial reading.** At the optimum, a single number, the value of an hour $\mu^\ast$, coordinates all decisions: every type is processed with the plan that is best when labour is charged $w_i + \mu^\ast$, and at most one type is processed in two ways because the hours run out part-way through it.

### 4.3 A threshold rule for reuse

Specialise to the three dispositions of Section 2 and consider a unit that is opened to level 2 anyway. Proposition 1 makes the choice separable across components.

**Proposition 4 (yield threshold) [proved].** Let $\omega = w_i + \mu$, $\bar v_j = v_j + L_j \lambda_j$, and assume $\bar v_j > m_j p_j$ (a good copy is worth more reused than as material). In a unit opened to level 2, reuse is at least as good as both sorting and leaving component $j$ if and only if

$$q_{ij} \;\ge\; q^{\dagger}_{ij}(\mu) \;=\; \frac{\kappa_j + \omega\, t_{j\mathsf{R}} - \min\{\omega\, t_{j\mathsf{S}},\; m_j (p_j + \tau)\}}{\bar v_j - m_j p_j}.$$

When $t_{j\mathsf{R}} \ge t_{j\mathsf{S}}$ the threshold is nondecreasing in $\mu$: the scarcer the labour, the higher the yield a component must show to be worth extracting and testing.

*Proof.* Per copy, the reduced values are $\phi^{\mathsf{R}} = q\bar v + (1-q) m p + \tau m - \kappa - \omega t_{\mathsf R}$, $\phi^{\mathsf{S}} = m(p + \tau) - \omega t_{\mathsf S}$ and $\phi^{0} = 0$ (indices dropped). $\phi^{\mathsf R} \ge \phi^{\mathsf S}$ rearranges to $q(\bar v - mp) \ge \kappa + \omega(t_{\mathsf R} - t_{\mathsf S})$, and $\phi^{\mathsf R} \ge 0$ to $q(\bar v - mp) \ge \kappa + \omega t_{\mathsf R} - m(p+\tau)$. Both hold if and only if $q(\bar v - mp)$ is at least the larger right-hand side, which is $\kappa + \omega t_{\mathsf R} - \min\{\omega t_{\mathsf S}, m(p+\tau)\}$; divide by $\bar v - mp > 0$. For monotonicity, the numerator is $\kappa + \omega t_{\mathsf R} - \min\{\omega t_{\mathsf S}, m(p + \tau)\}$, whose slope in $\omega$ is $t_{\mathsf R} - t_{\mathsf S} \ge 0$ where the minimum is $\omega t_{\mathsf S}$ and $t_{\mathsf R} \ge 0$ elsewhere. $\blacksquare$

The rule is what an operator can apply at the bench: *extract and test component $j$ when its observed good rate is above $q^\dagger_{ij}$*. The threshold is conditional on the unit being opened carefully; whether it is opened at all is decided by Proposition 1, where the opening set-up is weighed against the sum of the components' reduced values.

---

## 5. Unknown yields: learning while deciding

### 5.1 Model

The yield $q_{ij}$ is unknown. It is given a Beta prior whose mean comes from consumption records: if $c_{ij}$ copies of $j$ were consumed in $r_i$ repairs of type $i$, each containing $n_{ij}$ copies, the probability that a copy is defective in a *repaired* unit is estimated by $\hat d_{ij} = c_{ij}(1 - \pi^{\text{prev}}_j) / (r_i n_{ij})$, where $\pi^{\text{prev}}_j$ is the share of replacements made as a precaution, and

$$q^0_{ij} = \big(1 - \varrho_i\, \hat d_{ij}\big)_{[0,1]}\,(1 - b_j)\, r^{\text{test}}_j ,$$

with $\varrho_i \ge 1$ a factor for scrapped units being in worse condition than repaired ones, $b_j$ the breakage at extraction and $r^{\text{test}}_j$ the share of sound copies that pass the test. Teardown audits and routine tests then give binomial observations: of $n$ copies tested, $k$ good. With prior $\text{Beta}(q^0 N_0, (1 - q^0) N_0)$ the posterior is $\text{Beta}(q^0 N_0 + k,\ (1 - q^0) N_0 + n - k)$. **[implemented]** `erc/rex.py`, `erc/parametres.py::a_priori_rex`.

The prior is a modelling assumption with three identified weaknesses, all of which bias it in a known direction and are corrected by audit data: preventive replacement inflates $\hat d$; scrapped units are worse than repaired ones ($\varrho_i$ is not identified without an audit); and repairs that consumed nothing are missing from $r_i$.

### 5.2 The exploration problem

A copy's state is observed only if it is extracted and tested. A rule that follows the posterior mean never tests a component whose prior mean is below the threshold of Proposition 4, and therefore never corrects a pessimistic prior. This is a bandit problem with a resource constraint: the decision of each period is a solution of (P), and the feedback is the test outcome of the components that the solution chose to reuse.

**Algorithm TS-LP [implemented].** In each period: (1) draw $\tilde q_{ij}$ from the current posterior of every $(i,j)$; (2) solve (P) with $\tilde q$; (3) process the units accordingly; (4) update the posteriors with the test outcomes. `erc/rex.py::plan_thompson`.

Sampling from the posterior and solving a linear programme with the sample is the scheme analysed by Ferreira, Simchi-Levi and Wang (2018) for network revenue management, for which they establish Bayesian regret bounds; bandits with resource constraints are treated in general by Badanidiyuru, Kleinberg and Slivkins (2018), and posterior sampling by Russo and Van Roy (2014). **[literature]** Our feedback structure differs (the reward of a plan is observed component by component, and only for reused components), so we do **not** claim that those bounds apply. Regret is defined as

$$\text{Regret}(T) = \sum_{t=1}^{T} \Big( V(N_t, H; q) - \mathbb{E}\big[\,g(q)^{\top} x_t\,\big] \Big),$$

and is evaluated numerically. On a one-component synthetic benchmark with a prior mean of 0.2, a true yield of 0.6 and a threshold of 0.27, the rule that follows the prior and the greedy rule never test the component and lose 17.2 per copy, while Thompson sampling tests 97 % of copies, recovers $\hat q \approx 0.59$ and loses 0.6 per copy. These are simulation figures in arbitrary monetary units, not field results. **[implemented]** `erc/rex.py::simuler_politiques`. Extending the benchmark to full instances of (P) and comparing with a knowledge-gradient policy (Frazier, Powell and Dayanik 2008) is planned.

### 5.3 How the estimate is evaluated

The posterior is scored prequentially: each audit batch is predicted from what was known before it and only then used for updating. Reported: Brier score and logarithmic loss for grouped binomial outcomes, absolute error on the batch rate, and coverage of the 90 % predictive interval (Beta-binomial). Two references must be beaten: the prior alone, and the raw observed frequency. **[implemented]** `erc/rex.py::evaluer`; a test checks that a batch cannot influence its own prediction (`tests/test_stats.py`).

### 5.4 Quality of reused parts in service

A reusable part must also last once installed. The available field file records only early failures within a window after installation, in whole days, with no survivors. From such data the Weibull shape is estimable by a right-truncated discrete likelihood, $P(D = d \mid D \le W) = [F(d+1) - F(d)] / F(W+1)$, while the scale is not identifiable; early-failure rates of repaired or harvested parts relative to new ones are estimable when the number of parts installed is known. **[implemented]** `erc/fiabilite.py`; coverage of the 90 % interval for the shape is checked by simulation. The expected cost of an early failure is not yet a term of $\rho_{ij\mathsf R}$; it enters through the value $v_j$ supplied by the user. Making it explicit is an open item.

---

## 6. Irregular arrivals: what forecasting, buffering or reinforcement learning can gain

Scrapped units arrive irregularly. Let $A_t = (A_{it})_i$ be the arrivals of period $t$, with $\bar A = \lim_T \frac1T \sum_{t \le T} \mathbb{E} A_t$, and let $H$ hours be available in every period.

A **policy** chooses in each period, from the history, how many units of each type to process with each plan among the units on hand, within $H$ hours. Units not processed can be kept, within any storage limit, or released to the status quo. The **myopic** policy keeps no stock and solves (P) on each period's arrivals; it earns $V(A_t, H)$ in period $t$.

**Proposition 5 (fluid bound and variability gap) [proved].** For every policy $\pi$, the long-run average margin satisfies

$$\limsup_{T \to \infty} \frac1T\, \mathbb{E}^{\pi}\Big[\sum_{t=1}^{T} g^{\top} x_t\Big] \;\le\; V(\bar A, H),$$

and the myopic policy satisfies $\frac1T \sum_{t \le T} \mathbb{E}\, V(A_t, H) \le V\big(\frac1T \sum_{t\le T}\mathbb{E} A_t,\, H\big)$. Hence the gap

$$\Gamma \;=\; V(\bar A, H) \;-\; \lim_{T}\frac1T \sum_{t \le T} \mathbb{E}\,V(A_t, H) \;\ge\; 0$$

is an upper bound on what *any* policy that stores units, forecasts arrivals or is trained by reinforcement learning can gain per period over the myopic policy.

*Proof.* Fix $T$ and let $\bar x = \frac1T \sum_{t \le T} x_t$. Units processed by $T$ were received by $T$, so $\sum_s \bar x_{is} \le \frac1T \sum_{t \le T} A_{it}$; each period uses at most $H$ hours, so $\sum_{i,s} h_{is} \bar x_{is} \le H$. Taking expectations, $\mathbb{E}\bar x$ uses at most $H$ hours and at most $\bar A^T_i = \frac1T\sum_{t\le T}\mathbb{E}A_{it}$ units of type $i$; completing it with the plan $s^0$, which costs no hours and earns nothing, gives a feasible point of (P) with data $(\bar A^T, H)$ and the same objective. Therefore $\frac1T \mathbb{E}\sum_t g^\top x_t \le V(\bar A^T, H)$, and the first claim follows by continuity of $V$ as $\bar A^T \to \bar A$. The second claim is Jensen's inequality for the concave function $N \mapsto V(N, H)$ (Proposition 2), applied to the empirical distribution over periods and to the expectation. $\blacksquare$

**Consequences.**

1. $\Gamma$ is computable from the data: it is the difference between the annual model run on the average flow and the model replayed week by week. **[implemented]** `erc/ligne.py::resultat_par_periode` reports it as *Coût de la variabilité du flux*.
2. It settles when sophisticated dynamic control is worth building. If $\Gamma$ is small relative to $V$, no buffer, forecast or learned policy can add much, and the myopic rule is enough. If it is large, the candidates are, in increasing order of complexity: a buffer with a base-stock rule; a rolling-horizon version of (P) fed with forecasts; a stochastic programme on forecast scenarios; a policy trained by reinforcement learning on a simulator. Each is assessed by the share of $\Gamma$ it recovers. Reinforcement learning is a candidate only for the residual that the simpler policies leave.
3. The bound is not tight in general: a finite buffer cannot smooth arbitrarily long droughts. The true optimum lies between the myopic value and $V(\bar A, H)$.

**The dynamic model [not implemented].** With inventory $I_{it}$ of units on hand, released units $o_{it}$, a storage footprint $b_i$ and a storage limit $B$:

$$I_{i,t+1} = I_{it} + A_{it} - \sum_{s \ne s^0} x_{ist} - o_{it}, \qquad \sum_i b_i I_{it} \le B, \qquad \sum_{i,s} h_{is} x_{ist} \le H_t, \qquad x, o, I \ge 0 .$$

The state is the inventory together with the posterior on the yields. It is a Markov decision process whose exact solution is out of reach beyond small instances; the fluid bound is the benchmark against which approximate policies are measured.

---

## 7. Forecasting the arrivals

Weekly counts of scrapped units per type are short, low-count, intermittent series.

**Structural model.** A unit is scrapped when a unit received for repair is found beyond economic repair. With $E_{it}$ the units of type $i$ that reached a decision in period $t$ (repaired plus scrapped) and $\sigma_i$ the scrap rate,

$$A_{it} \mid E_{it}, \sigma_i \sim \text{Binomial}(E_{it}, \sigma_i), \qquad \sigma_i \sim \text{Beta}(\alpha, \beta),$$

with $(\alpha, \beta)$ shared across types and estimated from all of them, so that sparse types borrow strength. The inflow $E_{it}$ is a denser series, driven by the installed base, and is forecast separately; the predictive distribution of $A_{i,t+h}$ is Beta-binomial given a forecast of $E_{i,t+h}$. The same construction applies in production, where $E$ is the planned output of a stage and $\sigma$ its nonconformity rate.

**References to beat.** The mean of the history; Croston's method (Croston 1972), its bias-corrected form (Syntetos and Boylan 2005) and the Teunter–Syntetos–Babai variant (2011), which are the standard methods for intermittent demand; a pooled Gamma–Poisson model with negative-binomial predictive distribution; and zero-shot time-series foundation models, which need no training on our data: Chronos (Ansari et al. 2024), TimesFM (Das et al. 2024), Moirai (Woo et al. 2024), Toto (Cohen et al. 2024, 2025) and Timestral (Mistral AI 2026). **[implemented]** for the statistical methods and the evaluation, `erc/prevision.py`; the foundation models are run through an adapter on a machine that holds their weights and are not part of the test suite.

**What "competing with foundation models" can mean here [to measure].** Foundation models are trained on long, dense series; our series have a few dozen points and many zeros, and a known causal driver that a univariate zero-shot model does not see. The hypothesis to test is that the structural model matches or beats them on these series at a negligible computing cost. It is a hypothesis: public leaderboards, built on long and dense series, say nothing about series of this kind.

**Evaluation protocol.** Rolling origin with expanding window. Point accuracy by the root mean squared error relative to that of the historical mean; the absolute error is not used, because on intermittent counts it is minimised by forecasting zero. Probabilistic accuracy by the pinball loss on a grid of quantiles, which approximates the continuous ranked probability score, and by the coverage of the 80 % interval. These three are implemented. A fourth is planned and not yet coded: a decision-focused measure in the sense of Elmachtoub and Grigas (2022), the loss, in monetary units, of the plan computed from the forecast and evaluated on the realised arrivals, since a forecast is only as good as the decision it supports.

---

## 8. Knowledge acquisition: what is worth knowing

### 8.1 The missing knowledge

The recycling price $p_j$, the applicable regulatory route and the content in critical raw materials all depend on the **material composition** of component $j$, which the bill of materials does not give: it lists a company part number and a free-text description. Composition can be obtained by several means of very different cost and reliability: a rule on the description; analogy with an already validated part; a manufacturer's material declaration (IEC 62474, IPC-1752A) or data sheet found on the web; an extraction by a language model from a retrieved document; a check of that extraction by a second model; a human expert; a laboratory analysis.

### 8.2 A belief over composition, with sources of learned reliability

Let $C_j \in \mathcal{C}$ be the unknown material class of component $j$ with prior $\pi_0$. A piece of evidence $e$ is a pair (source type $u_e$, asserted class $c_e$). A source of type $u$ is correct with probability $r_u$ and otherwise asserts one of the other classes uniformly; given the truth, pieces of evidence of independent origin are independent. Then

$$P(C_j = c \mid E_j) \;\propto\; \pi_0(c) \prod_{e \in E_j} \Big( r_{u_e}\, \mathbb{1}\{c_e = c\} + \frac{1 - r_{u_e}}{|\mathcal{C}| - 1}\, \mathbb{1}\{c_e \ne c\} \Big).$$

This is the one-coin special case of the latent-class model of Dawid and Skene (1979) for combining fallible observers. The reliabilities are not assumed: each $r_u$ has a Beta posterior updated every time a human validates or corrects a component, so the system learns how far each kind of source can be trusted. **[implemented]** `erc/cortex.py`.

Three consequences are deliberate.

- **A language model is a source, never ground truth.** Its extractions and its validations enter the product with their own learned reliability. Ground truth is a human validation or a manufacturer's declaration.
- **Independence is enforced by provenance.** Ten web pages that reproduce one data sheet are one piece of evidence. Each claim records its origin, and claims of the same origin are counted once.
- **Unknown stays unknown.** A belief below the acceptance threshold produces no class, hence no price, hence no value for sorted recycling of that component.

The belief over classes induces a distribution on the price $p_j$ and on any other composition-dependent parameter.

### 8.3 Value of information

**Proposition 6 (information has a nonnegative value, with a computable bound) [proved].** For fixed $(N, H)$, $V$ is a convex function of the vector of values $(\rho_{ijd})$, and therefore of every parameter that enters these values affinely: recycling prices $p$, yields $q$, reuse values $v$. Let $\theta$ be such a parameter, uncertain with distribution $\pi$ and mean $\bar\theta$, and suppose the realised margin is affine in $\theta$ for a fixed solution. The expected value of perfect information,

$$\text{EVPI}(\pi) \;=\; \mathbb{E}_\pi\big[V(\theta)\big] - V(\bar\theta),$$

is nonnegative, and it is zero if and only if a solution that is optimal at $\bar\theta$ is optimal for $\pi$-almost every $\theta$. Moreover, if $\theta = p_j$ is the price of component $j \in \mathcal{J}_i$,

$$\text{EVPI}(\pi) \;\le\; N_i\, n_{ij}\, m_j \;\mathbb{E}_\pi\big|p_j - \bar p_j\big| ,$$

and if $\theta = q_{ij}$, $\ \text{EVPI}(\pi) \le N_i\, n_{ij}\, |\bar v_j - m_j p_j|\; \mathbb{E}_\pi|q_{ij} - \bar q_{ij}|$.

*Proof.* For a fixed feasible $x$ the objective $g(\theta)^\top x$ is affine in $\theta$, and $V$ is the pointwise maximum of these affine functions over the feasible set, hence convex. Let $x^\ast$ be optimal at $\bar\theta$. Then $V(\bar\theta) = g(\bar\theta)^\top x^\ast = \mathbb{E}_\pi[g(\theta)^\top x^\ast] \le \mathbb{E}_\pi[V(\theta)]$, with equality if and only if $g(\theta)^\top x^\ast = V(\theta)$ almost surely. For the bound, in any feasible solution at most $N_i n_{ij}$ copies of $j$ are diverted, and each contributes $m_j$ per unit of price, so $|g(p)^\top x - g(p')^\top x| \le N_i n_{ij} m_j |p_j - p_j'|$ for every feasible $x$; a maximum of functions with a common Lipschitz constant has that constant, so $V(p_j) - V(\bar p_j) \le N_i n_{ij} m_j |p_j - \bar p_j|$, and taking expectations gives the claim. The yield case is identical with the coefficient of $q_{ij}$ in $\rho_{ij\mathsf R}$, which is $\bar v_j - m_j p_j$. $\blacksquare$

The value without information is $V(\bar\theta)$ because the decision maker is risk-neutral and the margin is affine in $\theta$; for yields, the realised margin depends on realised good counts whose expectation is $q$.

**Use.** The expected value of a concrete acquisition (a web lookup, a model call, an audit of twenty units) is at most the EVPI, which is at most the bound. This gives a two-stage rule that keeps expensive calls to a minimum:

1. *Screen.* If the bound $N_i n_{ij} m_j \mathbb{E}|p_j - \bar p_j|$ is below the cost of the cheapest remaining acquisition, stop: nothing that could be learned about this component is worth its price. Most light, rare components stop here without any model call.
2. *Rank.* Otherwise compute the EVPI exactly, by solving (P) under each class in the support of the belief, and acquire, in decreasing order of EVPI per unit cost, until the EVPI falls below the cost or the belief passes the acceptance threshold.

**[implemented]** `erc/information.py` (bound and exact EVPI by scenarios), `erc/composition.py` (acquisition loop). Information value theory goes back to Howard (1966). What is specific here is that the value is computed through the operational model that will use the answer, so that characterisation effort goes to the components whose composition can change a decision.

### 8.4 Confidentiality constraint

A company part number and the description of an in-house design are not public. The acquisition layer therefore never sends them outside: outward queries use only the manufacturer's name and part number of purchased components, or a generic description, and components flagged as designed in-house are resolved from internal knowledge and human review only. **[implemented]** as a policy of `erc/composition.py`; a test checks that no internal identifier appears in an outgoing request.

---

## 9. Circularity and access as objectives

Three outcomes are linear in $x$ and are reported for every solution: the mass diverted from the bulk stream, $\sum_{i,s} k_{is} x_{is}$; the mass of critical or strategic raw materials directed to a recovery route; and the number of parts returned to service, $\sum_{i,s} u_{is} x_{is}$ with $u_{is} = \sum_{j : s_j = \mathsf R} n_{ij} q_{ij}$.

Because they are linear, the trade-off between margin and any of them is traced exactly by adding a weighted term to the objective or a lower bound as a constraint; by Proposition 3, with $R$ such constraints at most $R$ types are split, so the solutions stay simple to execute. The frontier answers a question that a single-objective optimum cannot: *how much margin does each additional part returned to service cost?* **[proved]** as a corollary of Proposition 3; **[not implemented]**.

Returning parts to service lowers the cost of repair and of refurbished systems. Whether and how much this improves access to equipment for hospitals with small budgets is an empirical question outside the model: the framework supplies the count of parts and its cost, and makes no claim about prices or access. **[to measure]**

---

## 10. From the repair centre to production

| Abstract object | Repair centre | Production (for example X-ray tube manufacturing) |
|---|---|---|
| unit type $i$ | type of scrapped FRU | nonconforming assembly at a given stage |
| arrivals $A_{it}$ | scrapped FRUs per week | nonconformities: output of the stage times its defect rate |
| inflow $E_{it}$ | units reaching a repair decision | units produced at the stage |
| component $j$ | part of the FRU | sub-assembly or material fraction |
| dispositions $\mathcal{D}$ | reuse in repair, sorted recycling, leave | rework, harvest for a new build, sorted recycling, scrap as is |
| access levels | rough or careful opening | disassembly depth; may be irreversible |
| yield $q_{ij}$ | share of extracted parts that pass test | share of harvested sub-assemblies that requalify |
| resource $H$ | operator hours outside the workload | rework stations, test benches |
| composition $C_j$ | drives recycler price and waste route | drives recovery route and handling rules for regulated materials |
| fixed cost $K$ | teardown and test line | rework cell |

What changes in production, and how the framework absorbs it:

- **More dispositions and deeper bills of materials.** The model is written for any finite $\mathcal{D}$ and $\mathcal{L}$; Proposition 1 keeps the pricing problem linear in the number of components. The current code fixes three dispositions and two opening levels; generalising them is a change of data structures, not of mathematics.
- **Mandatory routes.** A component whose class requires a licensed route has a restricted disposition set $\mathcal{D}_j(C_j) \subseteq \mathcal{D}$; this removes plans and leaves (P) unchanged in form. It is one more reason to know the composition before deciding.
- **Value added along the stages.** A unit scrapped late carries more value; types are indexed by stage.
- **Several coupling resources.** With $R$ resources Proposition 3 gives at most $R$ split types, and the dual has one price per resource.

None of this is implemented or validated on production data. **[to measure]**

---

## 11. What a journal submission requires

**Venue.** The *INFORMS Journal on Applied Analytics* publishes accounts of analytics in practice. Its submission guidelines state that a full-length application paper must be accompanied by a signed verification letter from the organisation, on its letterhead, confirming that the work is implemented, in use, and produces the stated benefits, and that the paper is not sent to review without it. A study on fictional or historical data does not qualify as a full paper there. A methodological paper (Sections 3 to 8) fits a venue that does not require implementation; a short practice summary is a third format.

**Before any submission, to be established with field data [to measure]:**

1. The input flow is verified: estimated against weighed mass within the stated margin, over at least a quarter.
2. Teardown audits give times per type and per component and at least a few hundred tested copies; the prequential scores of Section 5.3 are reported.
3. Recycler quotations exist for the sorted streams; compositions of the components that matter (by EVPI) are validated by a human or a manufacturer's declaration.
4. A pilot runs on one or two types for long enough to compare realised and predicted margin, with the finance function validating the valuation of reused parts.
5. The counterfactual is stated: what the bulk contract cost over the same period.
6. Forecasting methods are compared on the actual series with the protocol of Section 7.

**Contributions that the framework supports, stated at their current strength.**

- A disposition model for scrapped units with an opening set-up, a labour budget and three or more dispositions, with a solution structure simple enough to be executed on a shop floor (Propositions 1 to 4). The model class is known (multiple-choice knapsack relaxation); the application to repair-centre scrap with access levels and the resulting threshold rule are, to our knowledge, not in the product-recovery literature we cite, which should be confirmed by a systematic search.
- A certificate, computable from data, of how much dynamic control can add (Proposition 5), which turns "should we use reinforcement learning?" into a number.
- A value-of-information criterion that links a knowledge base fed by web retrieval and language models to the operational decision, and bounds the number of model calls worth making (Proposition 6).
- An open implementation with tests, including agreement with an exact solver.

---

## 12. Map to the implementation

| Section | Module | Checked by |
|---|---|---|
| 2–4 values, (P), multiplier, structure | `erc/ligne.py` | `tests/test_ligne.py`: exact LP solver on 600 instances, hand-computed cases, unknown-value matrix |
| 4 browser recomputation of (P) | `erc/outil_modele.js` | `tests/test_outil.py`: agreement with the Python model on random scenarios |
| 5 prior, posterior, TS-LP, scores | `erc/rex.py`, `erc/parametres.py` | `tests/test_stats.py` |
| 5.4 early failures, Weibull shape | `erc/fiabilite.py` | `tests/test_stats.py`: coverage by simulation |
| 6 week-by-week replay, variability gap | `erc/ligne.py::resultat_par_periode` | `tests/test_ligne.py`, `tests/test_information.py` |
| 7 forecasting and its evaluation | `erc/prevision.py` | `tests/test_prevision.py` |
| 8 belief, source reliability, acquisition | `erc/cortex.py`, `erc/composition.py` | `tests/test_cortex.py`, `tests/test_composition.py` |
| 8.3 EVPI and its bound | `erc/information.py` | `tests/test_information.py` |
| input flow verified against weighing | `erc/flux.py` | `tests/test_stats.py` |

---

## 13. Limits and open problems

1. **No field result.** All numbers in the repository are produced from fictional data. The mathematics is independent of them; every managerial claim is not.
2. **Enumeration limit.** Until Proposition 1 replaces the enumeration, a type with more than eight components is solved on its eight most valuable components.
3. **Independence (A3)** is doubtful: a unit scrapped for one cause often has correlated damage. A model with unit-level condition classes would relax it, in the spirit of quality grading (Ferguson et al. 2009), at the price of more parameters to learn.
4. **Regret guarantees** for TS-LP in our feedback model are not established.
5. **Demand for reused parts** is assumed to absorb the supply. A cap $\sum_i n_{ij} q_{ij} x \le D_j$ adds one constraint per saturated component and, by Proposition 3, one possible split type each.
6. **Source independence** in Section 8.2 holds only as far as provenance is traced; reliabilities are per source type, not per site.
7. **Composition as a single class** is a simplification; mass fractions over several materials call for a Dirichlet belief and a price that is a weighted sum, which keeps Proposition 6 unchanged since the price remains affine in the fractions.
8. **Risk neutrality.** A decision maker who must not lose money on the line would use a chance constraint or a conditional value-at-risk on the Monte-Carlo distribution that the package already produces.

---

## References

Status: **V** = bibliographic details verified against a publisher or repository page during the preparation of this document; **C** = cited from memory, details to be checked before submission.

- Ansari, A. F., et al. (2024). Chronos: Learning the language of time series. *Transactions on Machine Learning Research*. **C**
- Badanidiyuru, A., Kleinberg, R., Slivkins, A. (2018). Bandits with knapsacks. *Journal of the ACM* 65(3). **C**
- Cohen, B., et al. (2024). Toto: Time series optimized transformer for observability. arXiv:2407.07874. **V**
- Cohen, B., et al. (2025). This time is different: An observability perspective on time series foundation models. arXiv:2505.14766. **V**
- Croston, J. D. (1972). Forecasting and stock control for intermittent demands. *Operational Research Quarterly* 23(3), 289–303. **C**
- Das, A., Kong, W., Sen, R., Zhou, Y. (2024). A decoder-only foundation model for time-series forecasting. *ICML*. **C**
- Dawid, A. P., Skene, A. M. (1979). Maximum likelihood estimation of observer error-rates using the EM algorithm. *Applied Statistics* 28(1), 20–28. **C**
- Elmachtoub, A. N., Grigas, P. (2022). Smart "predict, then optimize". *Management Science* 68(1), 9–26. **C**
- Everett, H. (1963). Generalized Lagrange multiplier method for solving problems of optimum allocation of resources. *Operations Research* 11(3), 399–417. **C**
- Ferguson, M., Guide, V. D. R., Koca, E., Souza, G. C. (2009). The value of quality grading in remanufacturing. *Production and Operations Management* 18(3), 300–314. **C**
- Ferreira, K. J., Simchi-Levi, D., Wang, H. (2018). Online network revenue management using Thompson sampling. *Operations Research* 66(6), 1586–1602. **V**
- Fleischmann, M., et al. (1997). Quantitative models for reverse logistics: A review. *European Journal of Operational Research* 103(1), 1–17. **C**
- Frazier, P. I., Powell, W. B., Dayanik, S. (2008). A knowledge-gradient policy for sequential information collection. *SIAM Journal on Control and Optimization* 47(5), 2410–2439. **C**
- Guide, V. D. R., Van Wassenhove, L. N. (2009). The evolution of closed-loop supply chain research. *Operations Research* 57(1), 10–18. **C**
- Howard, R. A. (1966). Information value theory. *IEEE Transactions on Systems Science and Cybernetics* 2(1), 22–26. **C**
- Mistral AI (2026). Timestral. arXiv:2610.37585, and announcement on the publisher's site. **V** (existence and identifier; benchmark claims are the publisher's)
- Russo, D., Van Roy, B. (2014). Learning to optimize via posterior sampling. *Mathematics of Operations Research* 39(4), 1221–1243. **C**
- Sinha, P., Zoltners, A. A. (1979). The multiple-choice knapsack problem. *Operations Research* 27(3), 503–515. **C**
- Syntetos, A. A., Boylan, J. E. (2005). The accuracy of intermittent demand estimates. *International Journal of Forecasting* 21(2), 303–314. **C**
- Teunter, R. H., Syntetos, A. A., Babai, M. Z. (2011). Intermittent demand: Linking forecasting to inventory obsolescence. *European Journal of Operational Research* 214(3), 606–615. **C**
- Thierry, M., Salomon, M., van Nunen, J., Van Wassenhove, L. (1995). Strategic issues in product recovery management. *California Management Review* 37(2), 114–135. **C**
- Woo, G., et al. (2024). Unified training of universal time series forecasting transformers. *ICML*. **C**
- INFORMS Journal on Applied Analytics, submission guidelines, pubsonline.informs.org/page/ijaa/submission-guidelines, read in November 2026. **V**
- IEC 62474, *Material declaration for products of and for the electrotechnical industry*; IPC-1752A, *Materials declaration management*. **C**
