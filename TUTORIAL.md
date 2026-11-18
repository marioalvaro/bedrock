# Bedrock tutorial

A walkthrough of every screen in the app, in the order you will probably use them. For installation, configuration and the API, see the [README](README.md).

**Contents**
1. [Getting started](#1-getting-started)
2. [Add companies](#2-add-companies)
3. [Read the statements](#3-read-the-statements)
4. [Analyse: Ratios, Quality, Capital](#4-analyse-ratios-quality-capital)
5. [Fix and normalize the data](#5-fix-and-normalize-the-data)
6. [Manual input](#6-manual-input)
7. [Segments and KPIs](#7-segments-and-kpis)
8. [Seasonality](#8-seasonality)
9. [Comps](#9-comps)
10. [Guidance](#10-guidance)
11. [Scenarios](#11-scenarios)
12. [Forecast](#12-forecast)
13. [Valuation](#13-valuation)
14. [Backtest, snapshots and the audit log](#14-backtest-snapshots-and-the-audit-log)
15. [Review: the newest report](#15-review-the-newest-report)
16. [Notes and thesis checkpoints](#16-notes-and-thesis-checkpoints)
17. [Settings](#17-settings)
18. [Keeping data fresh](#18-keeping-data-fresh)
19. [Troubleshooting](#19-troubleshooting)
20. [Workflows from start to finish](#20-workflows-from-start-to-finish)

---

## 1. Getting started

Start the app as the [README](README.md#running) describes (`docker compose --profile prod up --build` is the shortest route) and open it in a browser: `http://localhost:8000` for the `prod` profile, `http://localhost:5173` for `dev`.

Log in with the password whose hash you put in `.env`. After that:

- The header has **Companies** (the home page), **Settings**, a theme toggle (light, dark, system) and **Log out**.
- A session ends after 12 hours of inactivity by default (`SESSION_IDLE_MINUTES`), and you are sent back to the login page.
- Five failed logins in 15 minutes lock the login for a while.

Bedrock is a single-user app. There are no accounts, only the one password.

## 2. Add companies

### From SEC

On the **Companies** page, type a ticker in the box (for example `AAPL`) and click **Add**. Bedrock looks the ticker up on SEC EDGAR, downloads every filing's XBRL facts and the daily prices, and adds the company to the list. The first load takes a little while for a company with a long history.

If it fails, the message says why:

| Message means | What to do |
|---|---|
| Unknown ticker (404) | SEC does not know it. A foreign issuer or a very new listing may not be there. If the company has no SEC filings, use a [manual company](#a-company-sec-does-not-cover). |
| Already followed (409) | It is in the list already. |
| Not configured (503) | Set `SEC_USER_AGENT` in `.env` to a contact email and restart. |
| Source failed (502) | SEC or yfinance did not answer. Try again. Nothing is kept if the first load fails. |

You can also add companies from a terminal: `cd backend && uv run bedrock add AAPL MSFT COST`.

### A company SEC does not cover

Click **Add manual company**, fill the form and click **Create**:

- **Ticker** and **Name**.
- **Fiscal year ends**: the month your annual period ends.
- **SIC (optional)**: a 4-digit industry code. It only matters for [peer suggestions](#9-comps).

The company appears in the list tagged `manual`. It starts empty. [Section 6](#6-manual-input) shows how to fill it.

### The company list

Each row shows the price, market cap, P/E, EV/EBITDA, TTM revenue growth and when it was last refreshed. A stat is blank when one of its inputs is missing, never zero. Click a ticker to open the company. The bin icon removes a company and its stored data (you can add it back later).

A company with a 10-K or 10-Q filed on EDGAR but not loaded yet carries a mark under its name, such as **10-Q filed Aug 1** (and "+1" when more are waiting). The app checks EDGAR's filing index once a day by itself; nothing is loaded until you refresh the company ([section 18](#18-keeping-data-fresh)).

## 3. Read the statements

A company page has a header and a row of tabs. The header shows:

- the ticker, name, price and market cap;
- the **new-filing mark** when a 10-K or 10-Q is waiting to be loaded (hover it: "Refresh to load it. The forecast is snapshotted first.");
- **Filings read: X of Y** and a **Read all filings** button (see [below](#reading-every-filing));
- **Refreshed** and the refresh button. After a refresh that loaded a new report, a line under the header says "Forecast snapshotted before loading the filing." with a **Review the result** link to the [Review tab](#15-review-the-newest-report).

The tabs are grouped by function, with a thin divider between groups:

**Overview** | **Income · Balance · Cash Flow · Segments** | **Ratios · Capital · Quality · Seasonality · Comps** | **Guidance · Forecast · Scenarios · Valuation · Backtest · Review** | **Notes**

### Overview

- **Key stats**: price, market cap, P/E, EV/EBITDA and revenue growth.
- **Data gaps**: what is missing and why ([below](#data-gaps)), with the lines to classify. The **Import** button sits here.
- **Adjustments**: the list of your normalization adjustments ([section 5](#adjustments-and-the-normalized-view)).
- **Corporate actions**: the stock splits that Bedrock uses to adjust share counts and per-share figures.

### The statement tabs

Income, Balance and Cash Flow share one toolbar:

| Control | Effect |
|---|---|
| **Annual / Quarterly / TTM** | The period type. TTM is not available for the balance sheet, which is a point in time. |
| **Reported / Normalized** | As filed, or with your [adjustments](#adjustments-and-the-normalized-view) applied. |
| **YoY** | Adds a year-on-year growth row under each line. |
| **Common size** | Adds each line as a percentage of revenue (income, cash flow) or of total assets (balance). Switch the base to **Parent row** to see a line as a share of its subtotal. |
| **Show empty lines** | Lines with no value in any period are hidden by default. |
| **Expand all / Collapse all** | Subtotals expand into their components. You can also click the arrow on a single row. |
| **Scale** | Show values in units, thousands, millions or billions. Per-share figures never scale. |
| **Bedrock rows / As reported** | Bedrock's statement (the default), or one filing exactly as filed ([below](#as-reported)). |
| **Import** | Opens the [manual import](#6-manual-input). |
| **CSV** | Downloads what the grid shows. |

On the balance sheet each period has a **balance check** (assets = liabilities + equity). Q4 and missing quarters are derived from the year-to-date figures, so Q1 + Q2 + Q3 + Q4 always equals the fiscal year.

### Where a number came from

The legend under the toolbar explains how a number is styled:

- **Reported**: as filed with the SEC.
- **Derived** (italic): worked out, such as Q4 = FY − Q1 − Q2 − Q3, or a formula over other lines.
- **~ Approximated**: rebuilt by a rule, such as a Q4 share count or the cover-page share count. Treat it as an estimate.
- **Imported**: typed by you through a file, where SEC had no value.
- **Inferred 0** (muted 0): a rule concluded the line is exactly zero, for example no non-controlling interest because the filing tags none.
- **Normalized**: changed by one of your adjustments.
- **Combined line** (a small dot before the number): the company reports this line together with another one, for example accounts payable with accrued liabilities. Hover the dot to see which. The other row's cell reads **incl. in <line>** in small grey type.
- **n/a**: the line cannot exist in that period (for example a quarterly value of a line the company reports only annually). Every other empty cell is "—".
- **AI classified** (a small ring before the number): the cell was filled by a line classification you accepted ([below](#classify-lines-optional)).

**Click any cell** and a side panel opens with its source XBRL tag, the filing it came from, the derivation formula and its inputs, **every filed version of the value** (restatements keep their history), the adjustments that touch it, and its notes. This is the quickest way to answer "why is this number what it is".

### Data gaps

On the Overview, **Data gaps** answers "what is missing":

- **Coverage**: how much of each statement has data, as two percentages: over every cell, and over the applicable cells, which leaves out cells that cannot hold a value (n/a and "incl. in"). It is split by how the data got there (reported, derived, imported, and so on) and by why a cell is empty (no filing data, not applicable, included in another line, structural, rule rejected, annual only, unclassified line, not reported). A list under the table explains each cause.
- **Rule warnings**: places where a gap-filling rule declined to fill a cell because the result would be implausible, with the reason.
- **Missing items**: lines with no value in some years.
- **Unmapped concepts**: tags in the latest 10-K that no line uses, with suggested line codes. Fixing a mapping is a developer task (see the `map-xbrl` skill in the README); for a one-off gap, [import the value](#6-manual-input).
- **Lines to classify**: lines on the face of a filed statement that no mapping places, with the latest value, period and filings. They can be mapped in the company's override file, or sent to a classifier ([below](#classify-lines-optional)).

### Reading every filing

Company facts, which a refresh reads, do not carry every number. **Read all filings** in the header also reads each 10-K and 10-Q's own XBRL: the company's extension tags and the lines on the face of the three statements. Those fill more cells and feed As reported and the lines to classify. It runs in the background (about one to two minutes per company); the count **Filings read: X of Y** rises while it runs, and the statements refresh when it finishes. From a terminal: `uv run bedrock backfill-filings AAPL` (or `--all`).

### As reported

On a statement tab, switch **Bedrock rows** to **As reported** to see one filing's statement exactly as the company filed it: its own lines, labels and order, and the filing's periods. Pick the filing in the selector (form, period end, filed date; newest first).

- The **Bedrock row** column says where each line lands: the Bedrock row(s) it maps to, "Other: …" when it sits in a block's other line, or **Not classified**.
- A total that does not equal the sum of its lines in that filing is marked ("Does not equal the sum of its lines in this filing").
- It is read only: no ratio, forecast, valuation or export takes a value from it, and the period, normalized, growth and common-size controls are hidden. The scale toggle still applies.

### Classify lines (optional)

The lines to classify can be sent to an AI classifier, only if you add a key for one in `.env` (`ANTHROPIC_API_KEY` for Claude, `TYPESAFE_API_KEY` for Jev, `OPENROUTER_API_KEY` for the OpenRouter models). Without a key the panel says "No classifier is configured. See Settings." and nothing is ever sent.

1. Under **Lines to classify** pick a classifier and click **Classify N lines**.
2. The confirmation shows the number of lines, the classifier, the estimated tokens and cost, the tokens left today and this month, and that the lines' labels, tags and amounts are sent to the provider. Click confirm.
3. While it runs the panel reads "Classifying… k of n". A line is never asked twice of the same classifier.
4. Each line then shows a **Proposal** (a Bedrock row, "Other", or "Combined: a + b") with its **Confidence**. **Accept**, **Reject**, or **Change** it to your own answer.

Nothing reaches the statements until you choose what they use, per company: **Off** (the default), **Accepted only**, or **All above 90 %** (also unreviewed answers at or above the confidence threshold). A classification only fills an empty cell, never moves a subtotal, and the cell is marked **AI classified**. Every decision is in the [audit log](#14-backtest-snapshots-and-the-audit-log), and a snapshot records the setting it was taken under. Token budgets per day and month cap spending ([Settings](#17-settings)).

## 4. Analyse: Ratios, Quality, Capital

### Ratios

Ratios by group (profitability, returns, liquidity, leverage, efficiency, cash flow) and **valuation multiples** (P/E, P/B, P/S, P/FCF, EV multiples, yields, PEG, invested capital and enterprise value) with the company's own historical range.

- **Annual / TTM** and **Reported / Normalized** switch the basis, and **CSV** exports.
- **Click a value** to see its formula, the numerator and denominator with every input down to the statement lines, a price with its date, and the reason when the value is empty.
- A ratio can carry a **caveat** where the company's structure makes it misleading, for example Deere's captive finance arm inflates debt-based ratios.

### Quality

Quality-of-earnings flags: accruals ratio, cash flow from operations against net income, receivables and inventory growing faster than revenue, goodwill as a share of assets, goodwill impairments, and stock-based compensation against revenue and cash flow. Each row shows its rule, and a period's value is highlighted when it crosses the warn or alert threshold (hover a value to see that period's levels). The thresholds are editable in [Settings](#17-settings), and so are your own rules.

Below the flags, **Off-balance-sheet items** is a log you keep by hand. Click **Add item** and choose a kind (lease, guarantee, VIE, purchase commitment or other), describe it, give an "as of" date and a source note.

### Capital

Where the cash goes: buybacks, dividends, the net change in share count (dilution or accretion), capex against depreciation and amortization, and acquisitions, shown as history and as a percentage of operating cash flow and free cash flow.

## 5. Fix and normalize the data

### Adjustments and the normalized view

Reported numbers sometimes hide a one-off. An **adjustment** is a correction you keep on the side, never overwriting the filing.

1. Click the cell on a statement (the line and period you want to change).
2. In the side panel click **Add adjustment**.
3. Enter the **Amount** (in the displayed sign: an expense is positive, so removing a one-off charge from SG&A is negative), a **Category** (one-off, restatement, reclass or other) and a **Reason** (required). Click **Save**.
4. Switch the toolbar to **Normalized**. The cell and its subtotals now include the adjustment, shown as normalized.

An adjustment to a component rolls up into its subtotals, so the statement still adds up. Adjust a component rather than a subtotal. You can edit or delete an adjustment in the panel or from the **Adjustments** list on the Overview. Ratios, comps and guidance can all be viewed on the normalized basis.

Some lines cannot be adjusted: the computed totals, EPS, share counts and dividends per share.

## 6. Manual input

Use it to:
- fill a gap in an SEC company (a line never tagged, or years from before XBRL);
- build a company that has no SEC data at all.

Imported numbers are USD. They never replace an SEC value and are stored apart from the SEC data, so you can always delete an import and go back.

### Step 1: get a template

Open the company, click **Import** (Overview or any statement tab). A panel opens.

Under **1. Template**:

- **Format**: Excel (`.xlsx`) or CSV.
- **Scale**: the unit your numbers are in. Choose *Millions* if you are copying from a report that says "in millions". The scale applies to dollar amounts and share counts, never to per-share figures.
- **Prefill with current values**: ticks the template with what the app shows today, so you see exactly where the gaps are. For a manual company there is nothing to prefill.

Click **Download template**.

### Step 2: understand the template

The Excel file has four sheets: `Instructions`, `IS`, `BS` and `CF`. A CSV is one file with the three statements one after the other, each row starting with `IS`, `BS` or `CF`.

**Instructions** (in a CSV: the first two lines) set the file's rules:

- `scale`: *units*, *thousands*, *millions* or *billions*.
- `fiscal_year_end`: the date your annual period ends, for example `2025-12-31`. **This is the only date you type.** Every column's start and end dates follow from it. Companies on a 52/53-week year (Apple's year ends on a Saturday near September 30) get close dates, which is fine for SEC companies. For exact dates see "Exact dates" below.
- The sheet also has a filled example of each statement.

**Each statement sheet** looks like this:

| | A | B | C | D | E | F, G, H … |
|---|---|---|---|---|---|---|
| `fiscal_year` row | | | | | | 2006, 2007, … |
| `fiscal_period` row | | | | | | FY, FY, … |
| title row | `code` | `label` | `parent` | `unit` | `children_complete` | FY06, FY07, … |
| one row per line | `revenue` | Revenue | | USD | | *your values* |

(A CSV has a leading `statement` column, so its values start one column to the right.)

- The columns are the **last 20 fiscal years**: first the 20 annual columns, then all the quarters (Q1, Q2, Q3, Q4 of a year, oldest year first). A whole row of annual values pastes in as one block.
- Fill only the columns you have. Blank cells are skipped.
- Type signs as the statements show them: capex, buybacks and dividends paid are **negative**.
- **Grey rows** are subtotals the app computes (for example total operating costs). If you type there the value is ignored with a warning. Subtotals such as *Gross profit* or *Total liabilities* accept a value; if the app can compute them from your other numbers it will, and your value is ignored.
- No line is mandatory, but ratios and flags need their inputs: the more lines you fill, the more of them work. Where a total can be worked out from its parts, you do not have to type it.
- To add a **column for a year before the 20-year window**, add a column with its `fiscal_year` and `fiscal_period`.

**Quarterly figures.** Type Q1, Q2 and Q3 for flows (income and cash flow), and Bedrock derives Q4 as the year minus those three. For the balance sheet, Q4 is the year-end balance, so type only FY.

### Step 3: upload and review

Under **2. Upload and review** choose the file and click **Preview**. Nothing is stored yet. The preview shows:

- **Cells that would be filled**: statement, line, period and value.
- **Ignored**: values you typed that were not used, with the reason: *SEC has a value* (the SEC figure stays) or *A formula gives another value*. It shows both numbers so you can see the difference.
- **Unchanged**: values equal to what is already shown (this is why a prefilled template re-imports cleanly).
- **Custom lines created** and **Parents filled from a complete breakdown** ([below](#custom-lines)).
- **Warnings**: a balance sheet that no longer balances, a cash flow that no longer foots, a quarter that disagrees with the year, and so on.

If the file has an error, the import is blocked and the panel lists each one by sheet, row and column, for example `IS, row 12, column G: not a number`. Fix the file and preview again. Common causes: a non-numeric cell, a duplicate period column, a custom line whose parent is not a leaf line, and a missing `fiscal_year_end`.

When the preview looks right, click **Import N cells**. The statements refresh immediately. **Nothing in the preview is stored until then.**

### Step 4: check the result

Imported numbers show in the **Imported** style. Click one to see which file it came from. Check the balance sheet's balance check, and look at **Data gaps** to see the coverage move.

Imports also feed the gap-filling rules: if you import the pieces of a total, the total fills in. An import counts as a single filing for those rules, so SEC and imported numbers are never mixed inside one calculation.

### History and undoing

The panel's **History** lists every import (file, date, scale, cell count). The bin icon deletes one: its values and custom lines go away and the cells fall back to SEC data or an earlier import. If you import the same cell twice, the newest import wins.

If SEC later publishes a value for a cell you had imported, SEC takes over automatically.

### Custom lines

A custom line is a breakdown you add under an existing line, for example splitting cost of revenue into materials and labour. In the template, add a row with:

- a **label** (the code is made from it; leave `code` blank),
- the line it splits in **parent** (a line that has no components of its own, or an earlier custom line),
- the values.

Custom lines appear indented under the parent with a **custom** marker. When a parent has custom lines and a value, an **Other** row shows the parent minus the lines you listed, so a partial breakdown still reconciles.

Set **`children_complete`** to `TRUE` on the *parent's* row to say the breakdown is complete. Then:
- if the parent is empty in a period, it is filled with the sum of the custom lines (shown as derived);
- if the parent already has a value and your lines do not add up to it, you get a warning and the parent keeps its value.

Custom lines show on the reported basis only. They are not adjustable and do not feed ratios directly; only a built parent does.

### Exact dates

By default, dates come from `fiscal_year_end`. If your year is 52 or 53 weeks and you want the exact dates, add two rows named `period_start` and `period_end` above the title row on a statement sheet and fill them for the columns that differ (both dates or neither).

### Worked example: a company SEC does not cover

1. On the Companies page click **Add manual company**. Ticker `ACME`, name `Acme Corp`, fiscal year ends *December*. Click **Create**.
2. Open ACME, click **Import** on the Overview, choose **CSV** and **Millions**, and download the template.
3. A full template has 100 period columns. For a first try you can delete the columns you do not need. This small file imports two years and a breakdown of cost of revenue (and is a complete example of the syntax):

   ```csv
   scale,millions
   fiscal_year_end,2025-12-31
   IS,fiscal_year,,,,,2024,2025
   IS,fiscal_period,,,,,FY,FY
   IS,code,label,parent,unit,children_complete,FY24,FY25
   IS,revenue,Revenue,,USD,,1000,1200
   IS,cost_of_revenue,Cost of revenue,,USD,TRUE,600,700
   IS,,Materials,cost_of_revenue,USD,,400,450
   IS,,Labor,cost_of_revenue,USD,,200,250
   IS,net_income,Net income,,USD,,150,210
   BS,fiscal_year,,,,,2024,2025
   BS,fiscal_period,,,,,FY,FY
   BS,code,label,parent,unit,children_complete,FY24,FY25
   BS,total_assets,Total assets,,USD,,2000,2300
   ```

   Reading it: revenue was USD 1,000 million in 2024; cost of revenue was 600, made of *Materials* 400 and *Labor* 200, and the `TRUE` marks that breakdown complete.
4. Upload it and click **Preview**. You should see the cells to fill and the two custom lines, *Materials* and *Labor*, under *Cost of revenue*. Click **Import**.
5. Open **Income**. Revenue and the cost of revenue breakdown are there, in the Imported style, with *Materials* and *Labor* indented under *Cost of revenue* and an *Other* row that is 0. The quarterly view has no values because you only gave annual figures.

Price-based stats (price, market cap, P/E) need a price: they stay blank unless the ticker exists on yfinance, in which case **Refresh** loads its prices. Market cap also needs a share count, so import `shares_outstanding` on the balance sheet if you want it.

### Tips

- Start with a **prefilled** template of an SEC company to see which cells are empty, fill only those, and re-import.
- Keep one file per source (a company report, a data service export) so History tells you where each number came from.
- If the preview ignores many values because SEC has them, that is the intended behaviour: SEC wins. Use an [adjustment](#adjustments-and-the-normalized-view) if you disagree with an SEC number.

## 7. Segments and KPIs

The **Segments** tab holds three kinds of breakdown that SEC facts do not give you in a usable form:

- **Business segments** and **Geographic segments**: revenue or operating income by segment. An **Unallocated** row reconciles the segments to the statement line.
- **KPIs**: any number you track, such as same-store sales, stores or average ticket.

Controls: **Annual / Quarterly**, **Scale**, **Add series**, **Import**, and on the annual view **Fill from quarterly**.

### Type it in

- Click **Add series** (or the button next to a block's title), pick the dimension and the metric, and name it. A KPI also needs a *Code* (lowercase letters, digits, underscores) and a *Unit* (USD, pct, count or USD per unit).
- Edit a value by editing its cell in the grid. The pencil and bin icons next to a series name rename and delete it.

### Paste or upload

Click **Import**. The sheet shows the format, an example and a downloadable template for each dimension. The header is `name, metric, unit` followed by one column per period, with headers like `FY2024` or `Q1 FY2024`:

```csv
name,metric,unit,FY2023,FY2024
iPhone,revenue,USD,"200,583","201,183"
Services,operating_income,USD,,"71,050"
```

Segments use `revenue` or `operating_income` and unit `USD`. KPIs use your own code as the metric. Pick the dimension and scale in the sheet, then paste the text or choose a file. The import is all or nothing: any error cancels it and is listed by row and column. A blank cell keeps the stored value.

### Fill from quarterly

On the annual view, **Fill from quarterly** sets each USD series' FY value to Q1 + Q2 + Q3 + Q4. If it would replace stored annual values you get a warning first (**Replace** confirms).

## 8. Seasonality

The **Seasonality** tab splits a quarterly line into its parts with an STL decomposition. Pick the **Line** (Revenue by default) and the K | M | B scale.

- **Seasonal strength**, from 0 (none) to 1 (strong).
- Three charts on one time axis: **Observed and trend**, **Seasonal** and **Residual**.
- **Seasonal factors**: for Q1..Q4, the amount the season adds or takes away, and that amount as a percentage of the trend.

A company like Costco, whose fiscal Q4 has an extra 16-week stretch, shows a strong pattern; the same seasonal index can drive the quarterly forecast ([Scenarios](#the-driver-grid)).

### Step by step: use seasonality in a quarterly forecast

1. Open **COST** (or any company you think is seasonal) and the **Seasonality** tab. Leave **Line** on Revenue.
2. Read the strength line. Close to 1 means the quarters follow a stable pattern; close to 0 means there is little to model, and a quarterly forecast built from the annual figure ÷ 4 is as good.
3. Look at **Residual**. Large, irregular spikes (an acquisition, a one-off) mean the factors are less reliable; note the periods.
4. Read the **Seasonal factors** row **% of trend**: for example Q4 +25 % says the fourth quarter runs a quarter above the trend.
5. Switch **Line** to the margins and days that drive the model (gross margin's inputs, SG&A, inventory days, …) and see which have a real pattern. Revenue needs nothing more: a forecast quarter already grows over the same quarter a year earlier, so its season carries over.
6. Go to **Scenarios**, pick your scenario and **Annual**. On a driver with a pattern (ratio and days drivers such as gross margin, SG&A or inventory days offer **STL** in their **Engine** select) choose **STL**. Its annual values stay Auto's.
7. Switch the grid to **Quarterly**. The quarters of a year set annually now follow the seasonal index; hover one: "FY27 value + the seasonal index (STL)". To type your own quarters instead, switch that year's **A | Q** to **By quarter**.
8. Check on **Forecast** › **Quarterly** that the quarters look like history, and that the **Integrity** panel's "Quarters = FY" check passes.

## 9. Comps

The **Comps** tab compares a company with a group of peers.

1. Click **New comps set** (or **New**) and give it a name.
2. In the editor, add peers from the **Add peer…** dropdown. A peer must be a company you follow. The dropdown lists **Suggested** peers first (companies with the same SIC code, from 4 digits down to 2, then closest by market cap, each tagged with how many digits matched) and then **Other followed** companies. Members show as chips you can remove. Click **Save members** to store the list.
3. The table compares the company with each peer on current valuation multiples and the latest TTM ratios, with the **Peer median** and **Peer range**. **Reported / Normalized** switches the basis.

You can have several sets per company, and **Rename** or **Delete** them. A manual company works as a target or as a peer. Add more companies from the Companies page to widen the pool.

## 10. Guidance

The **Guidance** tab logs what management said it expected and scores it against what happened.

Click **Add guidance** and fill in:

- **Metric**: a statement line (revenue, EPS, capex, …), an annual ratio, a quarterly margin, or a KPI.
- **Fiscal year** and **Period** (FY or a quarter). Only margins, lines and KPIs can be guided for a quarter.
- **Low** and **High**. A single number is low = high. Use the statement's sign convention: guidance of capex of $10–11 B is entered as −11 B to −10 B.
- **Given on** (a date), **Basis** (reported or normalized), **Direction** (higher is better, or lower is better; most metrics default correctly) and an optional **Source note**.

When the period is reported, each entry gets a verdict: **Beat** (better than the high end), **In range**, or **Miss** (worse than the low end), flipped for metrics where lower is better. The surprise is the actual against the midpoint. An entry with no actual yet is **Pending**.

If the company revises guidance, add another entry for the same metric and period: all are kept, and the one with the latest date counts in the summary.

**Actual vs predictions** at the top of the tab charts one metric at a time: pick **Annual** or **Quarterly** and a metric from **Metric**. Each period has bars side by side for the **Actual**, the analyst **Consensus** (its low to high range drawn as whiskers), management **Guidance** (the middle of the range) and, for a statement line such as revenue or EPS, your own **Forecast** (the Base case of your default scenario). The chart starts two years (or four quarters) before the latest reported period and runs through every period guided or forecast after it. Hover a period to see each value and range with its verdict, Beat in green and Miss in red. Older periods and every revision stay in the **Log** at the bottom of the tab.

The summary below the chart shows the counts and the **Hit rate** (beat plus in range, over all scored), overall and **by metric**.

### Step by step: log guidance and score it

1. After an earnings call, open the company's **Guidance** tab and click **Add guidance**.
2. **Metric**: pick it from the list (lines, ratios and KPIs are grouped). For revenue guidance of "$94–98 B for next quarter", pick Revenue.
3. **Fiscal year** and **Period**: the period guided (for example 2027, Q1). Annual ratios can only be guided for FY.
4. **Low** 94 and **High** 98 in the page scale (switch K | M | B first if needed). For an outflow such as capex, type it negative ("−11 to −10"), as the form reminds you.
5. **Given on**: the call's date. **Basis**: Reported, unless management guides an adjusted figure (then Normalized). **Direction** is pre-filled; check it (lower is better for costs). Add a **Source note** ("Q4 call, CFO").
6. **Save**. The entry shows **Pending** until the period is reported.
7. When management updates the range, add a new entry for the same metric and period with the new date; the old one stays in the **Log** as a revision.
8. After the period is filed and the company refreshed, the entry turns **Beat**, **In range** or **Miss**, with the **Surprise** against the midpoint. The summary's **Hit rate by metric** tells you which numbers management guides conservatively.

**Analyst consensus** is logged for you: every refresh, and the daily scheduled run, fetch Yahoo's analyst consensus for revenue and EPS and log it as guidance entries marked "Analyst consensus", with their own summary. A changed range is a new revision. Consensus entries cannot be edited or deleted, and EPS consensus is judged on the normalized basis (the street's adjusted figure).

## 11. Scenarios

The **Scenarios** tab is where you write your forecast as **drivers**, the assumptions the model turns into statements. Forecast and Valuation read them.

### Scenarios and cases

A company starts with one scenario, **Main**, and you can add more (**New**, with a name and a revenue build). Every scenario has three cases:

- **Base**: your central view. A driver you have not set takes a default, usually the mean of the last three actual years.
- **Bull** and **Bear**: they follow Base. Out of the box, Bull is Base + 3 pts revenue growth and + 1 pt gross margin, and Bear is Base − 3 pts and − 1 pt.

The toolbar has the scenario picker, **New**, **Rename**, **Delete** (not for Main), the **Base | Bull | Bear** toggle, **Reset <case>** (its drivers back to their defaults), the **K | M | B** scale, **Export** (CSV or Excel), **Import** and **Snapshot**.

**Snapshot** (the camera icon) saves the scenario's Base, Bull and Bear, and their valuations, as they stand, with an optional note (500 characters at most). A snapshot can never be changed; it is scored as actuals arrive, on the [Backtest tab](#14-backtest-snapshots-and-the-audit-log). The default scenario is also snapshotted for you when a refresh loads a new 10-K or 10-Q.

The picked scenario and case are in the address (`?scenario=…&case=…`), and the Forecast and Valuation tabs use the same ones.

### Step by step: build a Base case

1. Open the company and the **Scenarios** tab. **Main** is picked and **Base** is on. Switch the scale to **B** for a large company.
2. Choose the **Revenue build** under the toolbar: **Growth** to forecast one rate, **Segments** if you entered segment revenue on the Segments tab, or volume × price if you entered a count KPI and a price KPI.
3. Read the grid top to bottom. Muted values are defaults; hover one to see where it came from ("Default: ETS forecast · Auto: lowest holdout error", or "Default: mean of FY23–FY25").
4. Fix any red **Set** cell first: the model cannot run without it (DE needs a gross margin, for example).
5. Type your own view for the drivers that matter: revenue growth for each forecast year (`8` or `8%`), gross margin, opex as a share of revenue, working-capital days, capex as a share of revenue, buybacks. Press Tab or click away to commit; the value turns plain.
6. Watch for a dotted underline: your value is outside the engine's 90 % range. Hover it for the range, and open the chart icon in the label cell (**Engines** sheet) to see the history beside each engine's forecast before you keep it.
7. For a driver where you trust the statistics, pick an **Engine** instead of typing (for example **ARIMA** for a trending margin). It applies to all three cases.
8. Changed your mind on one row? Click its **Reset** button. On the whole case: **Reset Base** asks first ("Every driver of Base goes back to its default.").
9. Open **Forecast** to check the result ([section 12](#12-forecast)), then come back.

### Step by step: set Bull and Bear

1. Click **Bull** in the **Base | Bull | Bear** toggle. Every row shows Base's value plus an offset, muted italic ("Inherited from Base").
2. For a row you want to move with Base, keep **Mode** on **vs Base** and type the offset: `3` on revenue growth means Base + 3 pts in every year, even after you change Base.
3. For a row where the bull case is a different story (for example a margin that reaches 50 % by FY29 whatever Base does), switch **Mode** to **Value** and type the numbers.
4. Repeat on **Bear**. Then use **Compare** under the grid: pick a line and check that Bull > Base > Bear where you expect, and read any "Cases that cannot run".

### Step by step: forecast the next quarters

1. Switch the grid to **Quarterly**. The next 8 quarters are shown; years set annually show their quarters locked.
2. In the header of the first forecast year, switch **A | Q** to **By quarter**. Its four quarters become editable (seeded from the year).
3. Type the quarters you have a view on, typically from guidance for the next quarter. The year's annual figure is now the sum of its quarters.
4. To go back, switch the year to annual: a confirmation warns that the quarter values of Base, Bull and Bear are deleted.

### Step by step: edit drivers in a spreadsheet

1. **Export Excel** (or **Export CSV**) downloads the picked case's drivers.
2. Edit the values in your spreadsheet; keep the layout.
3. **Import**, choose the **Driver file**, click **Preview**. The sheet lists each change ("Revenue growth · FY27: 5.0% → 8.0%") or each error by row and column.
4. Click **Apply N changes**. Every change is in the [audit log](#14-backtest-snapshots-and-the-audit-log).

### Revenue build

Under the toolbar, pick how revenue is forecast; it applies to all three cases:

- **Growth**: one revenue growth rate per year.
- **Segments**: a growth rate per business or geographic segment (from the Segments tab).
- **Volume × price**: a count KPI times a price KPI (add both on the Segments tab first).

### The driver grid

Drivers are grouped (Revenue, Costs, Below the line, Working capital, Investment, Financing, Shareholders). Actual years are muted and read-only; the 5 forecast years (`FY27E`, tinted) are editable.

- Type a percent as `8` or `8%`, days as a number, amounts in the page scale. A cell commits when you leave it.
- How a value looks tells you where it comes from: **plain** you set it; **muted** a default; **muted italic** inherited from Base. Hover for the source ("Default: mean of FY23–FY25", "Inherited from Base").
- A red **Set** means the model needs a value there before it can forecast.
- A row you changed has a **Reset** button that returns it to its default.
- In Bull and Bear, each row has a **Mode**: **Value** (the case's own numbers) or **vs Base** (an offset, such as "+3.0 pts", that moves with Base).

**Engines.** In the annual grid, each driver with a default has an **Engine** select: **Auto** (the engine with the lowest error on held-out years; it shows what it picked, e.g. "Auto · ETS"), **Mean (3 yr)**, **ARIMA**, **ETS**, **Blend** and, for a seasonal line, **STL**. The choice applies to Base, Bull and Bear. A default cell's tooltip names its engine ("Default: ETS forecast"). A forecast value outside the engine's 90 % range is underlined with a dotted line, and its tooltip gives the range. The chart icon in a driver's label cell opens the **Engines** sheet: the history beside each engine's forecast, the case's values and the 90 % band, and a table of each engine's values and holdout error.

**Annual | Quarterly** switches the grid. The next 8 quarters can be set one by one: the **A | Q** switch in a year's header chooses whether that year is one annual value or four quarters. Returning a year to annual deletes its quarter values in all three cases, after a confirmation.

**Import** previews a CSV or Excel file of drivers ("Revenue growth · FY27: 5.0% → 8.0%") before you apply it; start from **Export** to get the layout.

### Compare

Below the grid, **Compare** charts one line (Revenue by default) for Bull, Base and Bear, and lists the key lines of each case. A case that cannot run says why.

## 12. Forecast

The **Forecast** tab shows the three statements the drivers produce: the same grids as Income, Balance and Cash Flow, with the forecast periods tinted and labelled `E`.

- Pick the scenario and case, the statement (**Income | Balance | Cash flow**) and **Annual | Quarterly**.
- The **Integrity** panel under the grid checks every forecast period: the balance sheet balances, cash and retained earnings roll forward, and (for years built from quarters) Q1..Q4 add up to the year. "All checks pass" is what you want to see; a failing check shows the difference.
- If a required driver is missing, the tab says "Set these drivers: …" with an **Open Scenarios** button that takes you to the same scenario and case.

### Step by step: check a forecast

1. Pick the scenario and case (the Scenarios tab's choice is carried over) and **Income**, **Annual**.
2. Read the first forecast year against the last actual: revenue growth, gross margin and operating margin should be the ones you set. Turn on **YoY** to see the growth row.
3. Switch to **Balance**. Look at cash: a forecast that piles up cash or runs it negative usually means buybacks, dividends or capex are off. Debt does not move by itself.
4. Switch to **Cash flow** and check that free cash flow (operating cash flow less capex) is plausible against history.
5. Open the **Integrity** panel: every period should read pass on the balance sheet, the cash and retained-earnings roll-forwards and, for quarterly years, Quarters = FY. A failure shows the difference; report it, as it is a bug, not an input problem.
6. Switch the case to **Bull** and **Bear** and repeat steps 2–4 quickly.

## 13. Valuation

The **Valuation** tab turns a forecast into a value per share and compares it with the latest close. It reads top to bottom in two levels.

### Target price by case

The top card compares the scenario's three cases: a row per method (DCF, P/E, EV/EBITDA, …), a column each for **Bull**, **Base** and **Bear**, each cell the value per share above its upside against the price (green above, red below). The price and its date are on the right. The shaded column is the case picked in the toolbar, the one the rest of the page details.

### The picked case

Everything under the **<Case> case · <Scenario> scenario** heading is about that case.

- **Target prices**: one tile per method, with the value per share in large type, its upside against the price, and what it rests on (the WACC, or a multiple and its year). A method that cannot value shows "—" and why.
- **DCF (FCFF)**, in four steps:
  1. **Discount rate**: the WACC and its parts (cost of equity = risk-free rate + beta × equity risk premium, after-tax cost of debt, and the debt and equity weights), or a rate you set directly.
  2. **Free cash flow to firm**: NOPAT, D&A, the change in working capital and capex per forecast year, then the discount years, factor and present value. If the current fiscal year is under way, its first column is the rest of that year.
  3. **Terminal value**: Gordon growth or an exit multiple of EBITDA, its present value, the other method's implied figure (a sanity check), and its share of enterprise value.
  4. **Equity bridge**: enterprise value, less debt, plus cash and short-term investments, less minority interest, = equity value, ÷ shares = value per share.
- **Multiples**: each target values a forecast year's metric at a multiple: P/E on net income, EV/EBITDA, P/FCF, EV/Sales. The multiple's source is shown under it. Own-history and peer multiples are trailing multiples applied to a forecast year, so read them as a cross-check.
- **Sensitivity**:
  - The **tornado** lists the inputs that move the DCF value per share most, at one step each: ±1 pt for a percentage driver, ±5 days, ±10 % for an amount, ±0.5 pt for the discount rate or terminal growth, ±1× for the exit multiple. Blue is the input one step lower, amber one step higher; hover a bar for both values. It shows the top 10; **Show all N** lists every input.
  - The **grid** shows the value per share over two inputs, 5 × 5, the current value at the ringed center. Pick **Rows** and **Columns** from the same inputs. It starts on discount rate × terminal growth (or exit multiple).
- **Inputs** are the valuation's own assumptions, per case:
  - **Discount rate**: WACC or a direct rate. For WACC: risk-free rate, equity risk premium, beta, cost of debt, tax rate and debt weight. Cost of debt, tax rate and debt weight come from the forecast and the market until you set them; hover to see from where.
  - **Terminal value**: Gordon growth or an exit multiple, and mid-year discounting.
  - **Multiples**: per target, a source (**Off**, **Manual** with your multiple, **Own history** at a percentile, **Peer median** of a comps set from the Comps tab) and the forecast year it applies to.

Inputs follow the same rules as drivers. Bull and Bear show Base's value (muted italic, "Inherited from Base") until you type their own. A field you set has a button to return it to Base's value (in Bull or Bear) or to the default (in Base). **Reset <Case> inputs** clears them all.

All three cases revalue when you change a driver or an input, and the K | M | B scale applies to the tables.

### Step by step: value a company

1. Build and check the forecast first ([sections 11](#11-scenarios) and [12](#12-forecast)). Open **Valuation** with **Base** picked.
2. **Discount rate.** In **Inputs**, keep **Discount method** on **WACC**. Check the **Risk-free rate** (from FRED's 10-year yield with `FRED_API_KEY`, else Yahoo's), the **Equity risk premium** and set **Beta** (1.0 by default). Hover **Cost of debt**, **Tax rate** and **Debt weight**: they come from the forecast and the market until you type them. If you prefer one number, switch to **Direct rate** and type the **Discount rate**.
3. **Terminal value.** **Terminal method**: **Gordon growth** with a **Terminal growth** at or below long-run nominal GDP (2–3 %), or **Exit multiple** with an **Exit multiple (EV/EBITDA)**. Keep **Mid-year discounting** on unless you have a reason.
4. Read the **DCF** card top to bottom: the WACC line, the free cash flow per year, the **Terminal value** and its share of enterprise value (above about 75 % the value rests mostly on the terminal assumptions), the other method's implied figure (a Gordon value implying a 30× exit multiple is a warning), then the **Equity bridge** to value per share.
5. **Multiples.** In **Inputs** › **Multiples**, P/E and EV/EBITDA start on **Own history** (the 50th percentile of the last 5 years). For each target pick a source: **Manual** with your multiple, **Own history** with a percentile and a lookback (3, 4, 5, 10 years or all), or **Peer median** with a **Comps set** from the Comps tab. Set the forecast **year** it applies to (1 = the first forecast year). P/FCF and EV/Sales start **Off**.
6. **Sensitivity.** The **tornado** shows which inputs move the value most. Spend your time on the top three. In the **grid** pick **Rows** and **Columns** (for example the discount rate and revenue growth FY27) to see the value over both.
7. **Bull and Bear.** Pick **Bull**: its inputs show Base's (muted italic). Change only what differs in that story (a lower beta, a higher exit multiple), then **Bear**.
8. Read the **Target price by case** card at the top: each method's value per share and upside for Bull, Base and Bear against the latest close. Wide gaps between methods are worth a note on the Notes tab.
9. Happy with it? Take a **Snapshot** on the Scenarios tab, so it is scored later ([section 14](#14-backtest-snapshots-and-the-audit-log)).

## 14. Backtest, snapshots and the audit log

The **Backtest** tab answers "how good are my forecasts?". A toggle at the top switches between three views.

### Backtest

Click **Run backtest** (it takes about 15 seconds). For each of the last 10 dates a 10-K was filed (except the newest), Bedrock rebuilds the company's data **as it was known that day**, restatements included, forecasts it with every engine (Auto, Mean, ARIMA, ETS, Blend, STL) and no input from you, and scores each forecast against what was reported later.

- Pick the **Metric** (a line or a driver), **Annual | Quarterly** (drivers are annual only) and the statistic: **MAPE** (average size of the error), **Bias** (its average sign: above zero the forecasts ran high) or **Hit rate** (the share of actuals inside the forecast range; only where ranges exist).
- The chart and the table show the statistic by **horizon** (1 year ahead, 2 years ahead, …), one line per engine. Hover a cell for how many forecasts it averages.
- The status line says when it last ran and how many method runs could not run (listed, collapsed, underneath). "A newer 10-K is filed: run again" means the result is out of date.

### Snapshots

The snapshots you took (and the automatic ones, tagged **Auto**: "Taken before a new filing was loaded"), newest first: when, scenario, note, data as of, scored periods and revenue MAPE, with the aggregate scores of Base, Bull and Bear on top. Click a row to open it: pick the case and a line to see the forecast against the actual per period, the error and whether the actual fell inside Bear–Bull, plus the case's valuations. The sheet also shows the line-classification setting the snapshot was taken under, and says so when it differs from today's.

### Audit log

Every change to a driver, an engine choice, a year's annual or quarterly mode, a valuation input, a scenario or an adjustment, and every line-classification decision and setting, newest first: when, what, where (scenario and case), from, to and **Rationale**. Type a rationale into any row (it saves when you leave the field) to record why you changed it. Filter with **Change type**; **Load more** pages back. Statement imports, segment values and Settings are not logged.

### Step by step: choose engines from the backtest

1. Open **Backtest** and click **Run backtest**. Wait about 15 seconds.
2. Leave **Metric** on Revenue, **Annual** and **MAPE**. In the chart, the lowest line at horizons 1–2 is the engine that forecast revenue best for this company on the data known at the time.
3. Switch **MAPE** to **Bias**. A line well above zero means that engine ran high; if your own Base is above that engine too, ask why.
4. Pick a driver in **Metric** (for example Gross margin) and compare again. **Hit rate**, where it is enabled, tells you how often the actual fell inside the engine's 90 % range.
5. On **Scenarios**, set the **Engine** of the drivers you leave to the statistics to the engine that won here (or keep **Auto**, which picks by holdout error).
6. Open **Runs that could not run** if the status line counts any: an origin before a line was reported says why.

### Step by step: score your own forecasts

1. Take a snapshot before each report: **Scenarios** › **Snapshot**, with a note such as "Before Q1 FY27". (After M7c the refresh also does this for the default scenario.)
2. After the report is loaded, open **Backtest** › **Snapshots**. The top table scores Base, Bull and Bear across all your snapshots; switch **Metric** and the statistic as on the Backtest view.
3. Click a snapshot row. Pick **Base**, then a line in **Line**: each period shows your forecast, the actual, the **Error** and whether the actual was **In range** (inside Bear–Bull). "—" means no actual yet.
4. Compare with the engines: if your Base MAPE is worse than the best engine's on the Backtest view, your adjustments are costing accuracy.
5. Open **Audit log** and add a **Rationale** to the changes that drove a big miss, so the next review has the reason.

## 15. Review: the newest report

The **Review** tab is one page for the newest 10-K or 10-Q, built for the day a company reports. Open it from the **Review the result** link after a refresh, or from the tab.

- **The heading**: the period, the form and its filing date, and the snapshot it is compared with ("Against the snapshot of <date> (<scenario>)", a link to the snapshot list). Without one it says "No snapshot was taken before this filing."
- **Key lines**: revenue, operating income, net income, diluted EPS, free cash flow, cash and total debt, each with the actual, its YoY growth, the snapshot's forecast, the error, the Bear–Bull range, the analyst **Consensus** and management **Guidance** (each a range with Beat, In range or Miss). The error is colored only when the actual fell outside Bear–Bull: red when the actual fell short, green when it beat.
- **Drivers that missed most**: forecast, actual, error and where the value came from (scored on a 10-K only; a 10-Q says so).
- **Restated**: the prior-period values this filing changed, before and after ("Showing 50 of N" when there are many).
- **Quality flags**: the flags whose severity changed, before → after, with their values.
- **Thesis**: the [checkpoints](#thesis-checkpoints) whose state changed, before → after.

Everything is computed when you open the page, so a guidance entry or a newer refresh shows straight away.

### Step by step: earnings day

1. On the company list, the company shows **10-Q filed …** (or 10-K) within a day of EDGAR listing the report (the check runs once a day per company while the app runs). You do not need to watch EDGAR yourself.
2. Before refreshing, log anything new from the call on **Guidance** (see [above](#step-by-step-log-guidance-and-score-it)), so the Review shows it.
3. Open the company and click the refresh button. The line "Forecast snapshotted before loading the filing." confirms your expectations were frozen first. If the mark stays, SEC's company facts are not out yet: try again later.
4. Click **Review the result**.
5. **Key lines**: read Error first. Uncolored means the actual fell inside your Bear–Bull range; red or green means outside. Then Consensus and Guidance: a line that beat consensus but missed your forecast says your Base was more optimistic than the street.
6. **Drivers that missed most** (after a 10-K): the assumptions to revisit. Open **Scenarios** and update them, case by case.
7. **Restated**: if prior values moved, earlier comparisons (and your snapshots' scores) now read the new figures. Large changes are worth a note.
8. **Quality flags**: a flag that moved to Warn or Alert deserves a look on the **Quality** tab.
9. **Thesis**: a checkpoint that went to **Broken** or **At risk** is the question for the day: does the thesis still hold? Write the answer on the **Notes** tab.
10. When the model is updated, take a new **Snapshot** with a note ("After Q1 FY27") so the next report is scored against your new view.

## 16. Notes and thesis checkpoints

The **Notes** tab holds your thesis: testable checkpoints on top, and a Markdown journal below.

### Thesis checkpoints

A checkpoint is a statement that must stay true for the thesis to hold, written in the same formula language as custom quality rules: two sides and one comparison (`>`, `>=`, `<`, `<=`). Examples: `gross_margin > 44%`, `yoy(shares_outstanding) < 0`, `net_debt_to_ebitda <= 2`, `roic > prev(roic) - 2%`.

1. Click **Add checkpoint**. Type the **Statement**, an optional **Label**, the **Frequency** (**TTM**, which moves with every 10-Q, or **Annual**, which moves only with a 10-K) and an optional **At-risk margin** (e.g. `1%`).
2. Save. A statement that does not parse is refused with the position of the error, and your text is kept.

Each checkpoint shows its **State** on the latest data, its value ("48.7% vs 44.0%", with the period), and **Since last filing**: "was Holding" when the newest report changed it, "New" when there was nothing to read before it.

- **Holding**: true, with room to spare.
- **At risk** (yellow): true, but within the at-risk margin, or, with no margin, the room has more than halved in a year (at that pace it breaks within a year).
- **Broken** (red): false.
- **Unknown**: no period has both values yet. A statement that no longer parses shows its error.

States are computed on every read, so they always match the latest data; the [Review tab](#15-review-the-newest-report) lists the ones a report changed.

### Step by step: turn a thesis into checkpoints

1. Write the thesis in one or two sentences in a note first, for example: "Services keep gross margin above 44 %, buybacks shrink the share count every year, and the balance sheet stays conservative."
2. Turn each claim into one comparison. Use the **Formula reference** on the Settings page for the names:
   - "gross margin above 44 %" → `gross_margin > 44%` (TTM);
   - "shares shrink every year" → `yoy(shares_outstanding) < 0` (Annual);
   - "conservative balance sheet" → `net_debt_to_ebitda <= 2` (TTM);
   - "returns are not eroding" → `roic > prev(roic) - 2%` (Annual: no more than 2 points below last year);
   - "growth stays positive" → `yoy(revenue) > 0` (TTM).
3. Choose the **Frequency**: **TTM** to hear about it at every 10-Q, **Annual** for claims that only make sense on a full year.
4. Decide whether you want an early warning. Without a margin, a checkpoint turns **At risk** when its room has more than halved in a year. With an **At-risk margin** (`1%` for gross margin above 44 %) it turns At risk once it is within 1 point of breaking.
5. Click **Add checkpoint**, fill it in, **Save**, and check the **Value** column reads what you expect ("48.7% vs 44.0%, TTM Q3 FY26"). An **Unknown** state means a name has no data for this company; pick another.
6. Give each a **Label** in plain words ("Margin holds"); the Review tab lists checkpoints by label.
7. On each report, read **Since last filing** here or the Review's **Thesis** block. Edit a checkpoint (pencil) when the thesis itself changes; delete (bin) one that no longer matters.

### The journal

- Click **New note**. Write the **Note**, set the **Note date** (today by default), and optionally link it with a **Subject** (a statement line, ratio, capital metric or quality rule) and a **Fiscal year** and **Period**. A note may link to a period alone.
- Filter the list by subject, year or period.
- A **marker** appears on any statement, ratio, capital or quality cell that has a note, and on a row whose line has notes. Click it to read them. A cell's side panel shows its notes too.

## 17. Settings

**Quality-of-earnings thresholds**: each built-in rule has a **Warn** and an **Alert** level and a direction. Edit the numbers and save, or reset a rule to its default.

**Custom rules**: write your own flag as a formula with `+ − × ÷`, brackets, `avg()`, `yoy()` and `prev()` over statement lines, metrics and ratios. Give it a label, a direction (above or below), a unit and the warn and alert levels. It then appears on every company's Quality tab next to the built-in rules. A warn or alert level may itself be a formula, for example `prev(sbc / revenue) + 2%`. An invalid formula is rejected with the position of the error. The **Formula reference** on the same page lists every name you can use (the same names work in [thesis checkpoints](#thesis-checkpoints)).

### Step by step: add a custom quality rule

1. Open **Settings** › **Custom rules** and click **Add rule**.
2. **Label**: what the flag means, for example "Capex below depreciation".
3. **Formula**: the value to watch, for example `-capex / d_and_a` (capex is negative in the statements, so the minus makes it positive). The **Formula reference** lists every name; `avg()`, `yoy()` and `prev()` compare across periods.
4. **Direction**: **Below** (flag when the value falls under the levels) here; **Above** for a ratio that is bad when high.
5. **Unit**: `pct` for a value shown as a percent, otherwise a multiple (`x`); here `x`.
6. The warn and alert levels: for example warn `1`, alert `0.8` (capex at 80 % of D&A). A level can be a formula itself, such as `avg(-capex / d_and_a) - 0.2`.
7. **Save**. An invalid formula is refused with the position of the error. The rule now shows on every company's **Quality** tab, colored where it crosses a level, and changes in it appear in the Review's **Quality flags**.

**Line classification**: each classifier with "key set" or "no key", the tokens used today and this month against the budgets (`CLASSIFY_DAILY_TOKENS`, `CLASSIFY_MONTHLY_TOKENS`) and the estimated cost this month. These budgets only limit this app; set a spending limit in the provider's console as well.

## 18. Keeping data fresh

- **Refresh** (the button in a company's header, or `bedrock refresh AAPL` / `bedrock refresh --all`) loads only new filings and prices. A price failure is a warning; an EDGAR failure is an error. It also re-reads the mapping files and fetches the analyst consensus.
- **When a refresh loads a new 10-K or 10-Q**, the default scenario is snapshotted first, on the data from before the filing, so the [Review tab](#15-review-the-newest-report) can compare the report with what you expected. A forecast that cannot run never blocks the refresh. Amendments and 8-Ks do not trigger it.
- **On a schedule** (while the app runs, unless `SCHEDULED_REFRESH=false`): prices hourly in US market hours and once after the close; once a day the market series behind the valuation defaults (risk-free rate, equity risk premium), the analyst consensus, and a read of each company's EDGAR filing index, which marks a company with an unloaded 10-K or 10-Q. The schedule never loads filings: that stays behind Refresh. A company page polls every 15 minutes, so an open page shows the new price and the mark.
- **Read all filings** (or `bedrock backfill-filings`) reads each filing's own XBRL in the background ([section 3](#reading-every-filing)). A refresh reads company facts only.
- A manual company refreshes prices only. Its statements change when you import.
- Raw SEC responses are cached under `DATA_DIR/raw/edgar/`, and the database is the SQLite file in `DATA_DIR`. Back up that folder to back up the app.

## 19. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Market cap, P/E or other stats are blank | An input is missing, usually shares outstanding or a price. Open the company's **Data gaps** and the ratio's cell details, which state the reason. |
| EV multiples are blank for some companies | Debt is not mapped in the latest period (Deere, Lockheed, RTX). [Import](#6-manual-input) the debt line, or ask for a mapping fix. |
| A cell shows `~` | It is an approximation (a rebuilt Q4 share count or EPS, or a cover-page share count). |
| Imported value not used | The preview says why: SEC has the value, or a formula already computes it. |
| Import blocked with errors | Read the list: it gives the sheet, row and column. |
| Balance sheet shows a mismatch after an import | The preview warned about it. Check that each period has total assets and the liabilities and equity lines, in the same scale. |
| 503 when adding a company | `SEC_USER_AGENT` is not set in `.env`. |
| Forecast or Valuation says "Set these drivers: …" | A required driver has no value in that case (DE needs a gross margin, for example). Click **Open Scenarios** and type one. |
| A multiple target shows "fewer than 3 years of history" | Own history needs at least three priced years. Set a manual multiple or a peer median instead. |
| No upside anywhere | No price is stored. Refresh the company. |
| The DCF says the discount rate must exceed the growth | Terminal growth is at or above the discount rate. Lower the growth or raise the rate. |
| The sensitivity grid says "Pick two different inputs" | Rows and Columns are the same input. |
| Logged out unexpectedly | The session expired after `SESSION_IDLE_MINUTES` of inactivity. |
| A new-filing mark stays after a refresh | SEC's company facts can lag the filing index by some hours. Refresh again later. |
| The Review says "No snapshot was taken before this filing." | The report was loaded before M7c, or the default scenario could not forecast at the time. Take snapshots before the next report. |
| A backtest origin says "Set these drivers: …" | That year's data lacks a line a driver needs (DE has no cost of revenue from FY2018). It is listed as a run that could not run. |
| "Classify N lines" is missing or disabled | No classifier key is set, a run is already going, or no line is left to ask. Settings shows the keys and the budgets. |
| A thesis checkpoint is Unknown | No period has both sides yet (a new metric, or a TTM read on a company with few quarters), or its statement no longer parses (its error is shown). |

## 20. Workflows from start to finish

Two complete paths through the app, each linking to the detailed steps above.

### From a ticker to a valued, tracked company

1. **Add the company** on the Companies page ([section 2](#2-add-companies)). Click **Read all filings** in its header and let it finish ([section 3](#reading-every-filing)).
2. **Check the data.** On the Overview, read **Data gaps**: coverage, rule warnings and missing items. Import what matters and is missing ([section 6](#6-manual-input)); classify lines if you use a classifier ([section 3](#classify-lines-optional)).
3. **Normalize** one-offs you do not want in the forecast base with adjustments ([section 5](#adjustments-and-the-normalized-view)).
4. **Understand the business.** Ratios, Quality, Capital, and Seasonality for a quarterly business ([section 8](#8-seasonality)). Enter segments and KPIs if you want a segment or volume × price build ([section 7](#7-segments-and-kpis)).
5. **Set up peers** on Comps ([section 9](#9-comps)): you will need them for peer-median multiples.
6. **Run the backtest** to see which engine forecasts this company best ([section 14](#step-by-step-choose-engines-from-the-backtest)).
7. **Build Base, then Bull and Bear** on Scenarios ([section 11](#step-by-step-build-a-base-case)), and **check the forecast** ([section 12](#step-by-step-check-a-forecast)).
8. **Value it** ([section 13](#step-by-step-value-a-company)).
9. **Write the thesis** as a note and as checkpoints ([section 16](#step-by-step-turn-a-thesis-into-checkpoints)). Log the latest guidance ([section 10](#step-by-step-log-guidance-and-score-it)).
10. **Take a snapshot** with a note. From now on the app snapshots again before each new report.

### Every quarter, when the company reports

1. The mark appears on the company list by itself.
2. Log new guidance from the call, then refresh the company.
3. Work through the Review tab ([section 15](#step-by-step-earnings-day)).
4. Update the drivers that missed, check the forecast, re-read the valuation.
5. Take a snapshot with a note. Every few quarters, look at **Backtest** › **Snapshots** to see whether your changes beat the engines ([section 14](#step-by-step-score-your-own-forecasts)).
