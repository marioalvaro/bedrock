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
8. [Comps](#8-comps)
9. [Guidance](#9-guidance)
10. [Notes](#10-notes)
11. [Settings](#11-settings)
12. [Keeping data fresh](#12-keeping-data-fresh)
13. [Troubleshooting](#13-troubleshooting)

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
- **SIC (optional)**: a 4-digit industry code. It only matters for [peer suggestions](#8-comps).

The company appears in the list tagged `manual`. It starts empty. [Section 6](#6-manual-input) shows how to fill it.

### The company list

Each row shows the price, market cap, P/E, EV/EBITDA, TTM revenue growth and when it was last refreshed. A stat is blank when one of its inputs is missing, never zero. Click a ticker to open the company. The bin icon removes a company and its stored data (you can add it back later).

## 3. Read the statements

A company page has a header (ticker, name, price, market cap, **Refreshed**, and a refresh button) and a row of tabs:

**Overview · Income · Balance · Cash Flow · Ratios · Quality · Capital · Segments · Comps · Guidance · Notes**

### Overview

- **Key stats**: price, market cap, P/E, EV/EBITDA and revenue growth.
- **Data gaps**: what is missing and why ([below](#data-gaps)). The **Import** button sits here.
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

**Click any cell** and a side panel opens with its source XBRL tag, the filing it came from, the derivation formula and its inputs, **every filed version of the value** (restatements keep their history), the adjustments that touch it, and its notes. This is the quickest way to answer "why is this number what it is".

### Data gaps

On the Overview, **Data gaps** answers "what is missing":

- **Coverage**: how much of each statement has data, split by how it got there (reported, derived, imported, and so on).
- **Rule warnings**: places where a gap-filling rule declined to fill a cell because the result would be implausible, with the reason.
- **Missing items**: lines with no value in some years.
- **Unmapped concepts**: tags in the latest 10-K that no line uses, with suggested line codes. Fixing a mapping is a developer task (see the `map-xbrl` skill in the README); for a one-off gap, [import the value](#6-manual-input).

## 4. Analyse: Ratios, Quality, Capital

### Ratios

Ratios by group (profitability, returns, liquidity, leverage, efficiency, cash flow) and **valuation multiples** (P/E, P/B, P/S, P/FCF, EV multiples, yields, PEG, invested capital and enterprise value) with the company's own historical range.

- **Annual / TTM** and **Reported / Normalized** switch the basis, and **CSV** exports.
- **Click a value** to see its formula, the numerator and denominator with every input down to the statement lines, a price with its date, and the reason when the value is empty.
- A ratio can carry a **caveat** where the company's structure makes it misleading, for example Deere's captive finance arm inflates debt-based ratios.

### Quality

Quality-of-earnings flags: accruals ratio, cash flow from operations against net income, receivables and inventory growing faster than revenue, goodwill as a share of assets, goodwill impairments, and stock-based compensation against revenue and cash flow. Each row shows its rule, and a period's value is highlighted when it crosses the warn or alert threshold (hover a value to see that period's levels). The thresholds are editable in [Settings](#11-settings), and so are your own rules.

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

## 8. Comps

The **Comps** tab compares a company with a group of peers.

1. Click **New comps set** (or **New**) and give it a name.
2. In the editor, add peers from the **Add peer…** dropdown. A peer must be a company you follow. The dropdown lists **Suggested** peers first (companies with the same SIC code, from 4 digits down to 2, then closest by market cap, each tagged with how many digits matched) and then **Other followed** companies. Members show as chips you can remove. Click **Save members** to store the list.
3. The table compares the company with each peer on current valuation multiples and the latest TTM ratios, with the **Peer median** and **Peer range**. **Reported / Normalized** switches the basis.

You can have several sets per company, and **Rename** or **Delete** them. A manual company works as a target or as a peer. Add more companies from the Companies page to widen the pool.

## 9. Guidance

The **Guidance** tab logs what management said it expected and scores it against what happened.

Click **Add guidance** and fill in:

- **Metric**: a statement line (revenue, EPS, capex, …), an annual ratio, a quarterly margin, or a KPI.
- **Fiscal year** and **Period** (FY or a quarter). Only margins, lines and KPIs can be guided for a quarter.
- **Low** and **High**. A single number is low = high. Use the statement's sign convention: guidance of capex of $10–11 B is entered as −11 B to −10 B.
- **Given on** (a date), **Basis** (reported or normalized), **Direction** (higher is better, or lower is better; most metrics default correctly) and an optional **Source note**.

When the period is reported, each entry gets a verdict: **Beat** (better than the high end), **In range**, or **Miss** (worse than the low end), flipped for metrics where lower is better. The surprise is the actual against the midpoint. An entry with no actual yet is **Pending**.

If the company revises guidance, add another entry for the same metric and period: all are kept, and the one with the latest date counts in the summary. The top of the tab shows the counts and the **Hit rate** (beat plus in range, over all scored), overall and **by metric**.

## 10. Notes

The **Notes** tab is your thesis journal, in Markdown.

- Click **New note**. Write the **Note**, set the **Note date** (today by default), and optionally link it with a **Subject** (a statement line, ratio, capital metric or quality rule) and a **Fiscal year** and **Period**. A note may link to a period alone.
- Filter the list by subject, year or period.
- A **marker** appears on any statement, ratio, capital or quality cell that has a note, and on a row whose line has notes. Click it to read them. A cell's side panel shows its notes too.

## 11. Settings

**Quality-of-earnings thresholds**: each built-in rule has a **Warn** and an **Alert** level and a direction. Edit the numbers and save, or reset a rule to its default.

**Custom rules**: write your own flag as a formula with `+ − × ÷`, brackets, `avg()`, `yoy()` and `prev()` over statement lines, metrics and ratios. Give it a label, a direction (above or below), a unit and the warn and alert levels. It then appears on every company's Quality tab next to the built-in rules. A warn or alert level may itself be a formula, for example `prev(sbc / revenue) + 2%`. An invalid formula is rejected with the position of the error. The **Formula reference** on the same page lists every name you can use.

## 12. Keeping data fresh

- **Refresh** (the button in a company's header, or `bedrock refresh AAPL` / `bedrock refresh --all`) loads only new filings and prices. A price failure is a warning; an EDGAR failure is an error. It also re-reads the mapping files.
- A manual company refreshes prices only. Its statements change when you import.
- Raw SEC responses are cached under `DATA_DIR/raw/edgar/`, and the database is the SQLite file in `DATA_DIR`. Back up that folder to back up the app.

## 13. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Market cap, P/E or other stats are blank | An input is missing, usually shares outstanding or a price. Open the company's **Data gaps** and the ratio's cell details, which state the reason. |
| EV multiples are blank for some companies | Debt is not mapped in the latest period (Deere, Lockheed, RTX). [Import](#6-manual-input) the debt line, or ask for a mapping fix. |
| A cell shows `~` | It is an approximation (a rebuilt Q4 share count or EPS, or a cover-page share count). |
| Imported value not used | The preview says why: SEC has the value, or a formula already computes it. |
| Import blocked with errors | Read the list: it gives the sheet, row and column. |
| Balance sheet shows a mismatch after an import | The preview warned about it. Check that each period has total assets and the liabilities and equity lines, in the same scale. |
| 503 when adding a company | `SEC_USER_AGENT` is not set in `.env`. |
| Logged out unexpectedly | The session expired after `SESSION_IDLE_MINUTES` of inactivity. |
