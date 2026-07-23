"""Render the PA Housing dashboard as a self-contained HTML file.

The pipeline calls build_dashboard() after writing its CSVs; the output at
reports/pa_housing_dashboard.html opens in any browser with no dependencies.
All data is embedded as JSON; forensic flags come from reporting.forensic.
The file is a small multi-view app (Overview / Regions / County Detail)
navigated by hash routing, so every view is just JS show/hide over the same
embedded SUMMARY / MONTHLY / REGIONAL blobs — nothing is computed twice.
"""

import json
import logging
import re
from datetime import date
from pathlib import Path

import pandas as pd

from data_platform.pipelines.regions import add_region, regional_summary
from data_platform.reporting.forensic import run_forensic_tests

logger = logging.getLogger(__name__)

TREND_YEARS = 10  # embed this many years of history, quarterly


def slugify(name: str) -> str:
    """URL-safe slug for hash routing, e.g. 'Forest County' -> 'forest-county'."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _to_quarterly_series(df: pd.DataFrame, group_col: str) -> dict[str, list]:
    """Pre-aggregate monthly rows to quarterly means per group_col (keeps HTML small)."""
    working = df.copy()
    working["date"] = pd.to_datetime(working["date"])
    cutoff = working["date"].max() - pd.DateOffset(years=TREND_YEARS)
    working = working[working["date"] >= cutoff]
    working["quarter"] = working["date"].dt.to_period("Q").dt.to_timestamp()
    grouped = working.groupby([group_col, "quarter"], as_index=False)["zhvi"].mean()
    out: dict[str, list] = {}
    for key, grp in grouped.groupby(group_col):
        out[key] = [
            {"d": ts.strftime("%Y-%m"), "v": round(v)}
            for ts, v in zip(grp["quarter"], grp["zhvi"], strict=True)
        ]
    return out


def _records(df: pd.DataFrame) -> list[dict]:
    """DataFrame -> JSON-safe records (NaN -> None; json.dumps would emit invalid NaN)."""
    return df.astype(object).where(df.notna(), None).to_dict(orient="records")


def _amenities_by_county(amenities: pd.DataFrame) -> dict[str, list]:
    """Group raw OSM amenity elements by county, for the County Detail expandable names list."""
    return {
        county: _records(grp[["category", "sport", "name"]])
        for county, grp in amenities.groupby("county")
    }


def build_dashboard(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    amenities: pd.DataFrame,
    out_path: Path = Path("reports/pa_housing_dashboard.html"),
) -> Path:
    tested = add_region(run_forensic_tests(summary))
    tested["slug"] = tested["region"].map(slugify)
    tested["latest_date"] = tested["latest_date"].astype(str)

    monthly_r = add_region(monthly)

    regional_df = regional_summary(tested)
    regional_df["slug"] = regional_df["pa_region"].map(slugify)

    amenities_as_of = (
        str(amenities["fetched_date"].iloc[0])
        if "fetched_date" in amenities.columns and len(amenities)
        else "unknown"
    )
    meta = {
        "generated": date.today().isoformat(),
        "latest_date": str(summary["latest_date"].iloc[0]),
        "county_count": int(len(summary)),
        "amenities_as_of": amenities_as_of,
    }
    regional = {
        "summary": _records(regional_df),
        "monthly": _to_quarterly_series(monthly_r, "pa_region"),
    }
    html = (
        _TEMPLATE.replace("__SUMMARY_JSON__", json.dumps(_records(tested)))
        .replace("__MONTHLY_JSON__", json.dumps(_to_quarterly_series(monthly, "region")))
        .replace("__REGIONAL_JSON__", json.dumps(regional))
        .replace("__AMENITIES_JSON__", json.dumps(_amenities_by_county(amenities)))
        .replace("__META_JSON__", json.dumps(meta))
    )
    out_path.parent.mkdir(exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    logger.info("Wrote dashboard: %s (%.0f KB)", out_path, out_path.stat().st_size / 1024)
    return out_path


_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PA Housing Market Tracker</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.5.1"></script>
<style>
:root{--bg:#f4f5f7;--bg-card:#fff;--bg-header:#1b2a41;--text:#1f2430;--text-2:#6b7280;
--on-dark:#f5f7fa;--pos:#0e7c7b;--neg:#c0392b;--warn:#b7791f;--radius:10px;--gap:16px}
*{margin:0;padding:0;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
body{background:var(--bg);color:var(--text);padding:20px}
.wrap{max-width:1200px;margin:0 auto}
.hdr{background:var(--bg-header);color:var(--on-dark);padding:20px 24px;border-radius:var(--radius);
margin-bottom:var(--gap);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:12px}
.hdr h1{font-size:20px;font-weight:600}.hdr .sub{font-size:12px;opacity:.75;margin-top:4px}
.hdr .chip{display:inline-block;margin-top:8px;font-size:12px;background:rgba(255,255,255,.12);
padding:4px 10px;border-radius:12px}
.tabs{display:flex;gap:6px}
.tabs button{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.25);color:var(--on-dark);
padding:7px 14px;border-radius:6px;font-size:13px;cursor:pointer}
.tabs button:hover{background:rgba(255,255,255,.18)}
.tabs button.active{background:rgba(255,255,255,.28);font-weight:600}
.view{display:none}
.view.active{display:block}
.downloads{margin-bottom:var(--gap);font-size:12px}
.downloads a{color:var(--text-2);text-decoration:none;margin-right:10px;padding:5px 12px;
background:var(--bg-card);border-radius:6px;box-shadow:0 1px 3px rgba(0,0,0,.08);display:inline-block}
.downloads a:hover{color:var(--text)}
.county-link{color:var(--text);text-decoration:none;border-bottom:1px dotted var(--text-2)}
.county-link:hover{color:var(--pos);border-bottom-color:var(--pos)}
.filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:var(--gap)}
.filters label{font-size:12px;color:var(--text-2)}
.filters select{padding:6px 10px;border:1px solid #d7dbe0;border-radius:5px;
background:#fff;color:var(--text);font-size:13px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:var(--gap);margin-bottom:var(--gap)}
.kpi{background:var(--bg-card);border-radius:var(--radius);padding:18px 22px;box-shadow:0 1px 3px rgba(0,0,0,.08)}
.kpi .lbl{font-size:12px;color:var(--text-2);text-transform:uppercase;letter-spacing:.5px;margin-bottom:4px}
.kpi .val{font-size:26px;font-weight:700}.kpi .note{font-size:12px;color:var(--text-2);margin-top:3px}
.kpi.flagged .val{color:var(--warn)}
.charts{display:grid;grid-template-columns:1.2fr 1fr;gap:var(--gap);margin-bottom:var(--gap)}
.card{background:var(--bg-card);border-radius:var(--radius);padding:18px 22px;
box-shadow:0 1px 3px rgba(0,0,0,.08);margin-bottom:0}
.card h3{font-size:14px;font-weight:600;margin-bottom:4px}
.card .hint{font-size:12px;color:var(--text-2);margin-bottom:12px}
.card.spaced{margin-bottom:var(--gap)}
canvas{max-height:320px}
#scatter,#bars{cursor:pointer}
.anomaly{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid #f0f0f0;font-size:13px;line-height:1.45}
.anomaly:last-child{border-bottom:none}
.badge{flex:0 0 auto;font-size:11px;font-weight:700;padding:2px 8px;border-radius:10px;height:fit-content;margin-top:2px}
.badge.red{background:#fdecea;color:var(--neg)}.badge.amber{background:#fdf3e3;color:var(--warn)}
.badge.grey{background:#eef0f3;color:var(--text-2)}
.tbl-wrap{overflow-x:auto}
table{width:100%;border-collapse:collapse;font-size:13px}
thead th{text-align:left;padding:9px 12px;border-bottom:2px solid #dee2e6;color:var(--text-2);
font-size:11.5px;text-transform:uppercase;letter-spacing:.5px;cursor:pointer;white-space:nowrap;user-select:none}
thead th:hover{color:var(--text)}
tbody td{padding:9px 12px;border-bottom:1px solid #f0f0f0;white-space:nowrap}
tbody tr:hover{background:#f8f9fa}
.bar-cell{position:relative;min-width:130px}
.bar{position:absolute;left:0;top:15%;height:70%;background:rgba(14,124,123,.18);border-radius:3px;z-index:0}
.bar.negbar{background:rgba(192,57,43,.18)}
.bar-cell span{position:relative;z-index:1}
.flag-dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:middle}
.flag-dot.red{background:var(--neg)}.flag-dot.amber{background:var(--warn)}.flag-dot.none{background:#d6dade}
.ftr{font-size:12px;color:var(--text-2);margin-top:var(--gap);line-height:1.5}
.region-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:var(--gap);margin-bottom:var(--gap)}
.region-card{background:var(--bg-card);border-radius:var(--radius);padding:16px 18px;
box-shadow:0 1px 3px rgba(0,0,0,.08);cursor:pointer;transition:box-shadow .15s}
.region-card:hover{box-shadow:0 4px 12px rgba(0,0,0,.12)}
.region-card h4{font-size:14px;font-weight:600;margin-bottom:10px}
.region-card .rc-stats{display:flex;flex-wrap:wrap;gap:10px 18px;font-size:11.5px;color:var(--text-2);margin-bottom:10px}
.region-card .rc-stats strong{display:block;font-size:16px;color:var(--text);font-weight:700}
.region-card canvas{max-height:44px}
.county-picker-row{display:flex;gap:10px;align-items:center;margin-bottom:var(--gap);flex-wrap:wrap}
.county-picker-row select{padding:7px 10px;border:1px solid #d7dbe0;border-radius:6px;font-size:13px;flex:1;min-width:200px}
.county-picker-row button{padding:7px 16px;border:1px solid #d7dbe0;border-radius:6px;background:#fff;
cursor:pointer;font-size:13px}
.county-picker-row button:hover:not(:disabled){background:#f4f5f7}
.county-picker-row button:disabled{opacity:.35;cursor:default}
.region-context{font-size:13px;color:var(--text-2);margin-bottom:var(--gap)}
.bench-grid{display:grid;grid-template-columns:1fr 1fr;gap:var(--gap);margin-bottom:var(--gap)}
.amenity-groups{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.amenity-group{background:var(--bg);border-radius:6px;padding:8px 12px;font-size:13px}
.amenity-group summary{cursor:pointer;font-weight:600;list-style:none}
.amenity-group summary::-webkit-details-marker{display:none}
.amenity-group .amenity-count{float:right;color:var(--text-2);font-weight:400}
.amenity-group ul{margin:8px 0 0 16px;font-size:12.5px;color:var(--text-2);max-height:160px;overflow-y:auto}
@media(max-width:820px){.charts{grid-template-columns:1fr}.bench-grid{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div>
      <h1>PA Housing Market Tracker</h1>
      <div class="sub" id="subline"></div>
      <div class="chip" id="top-mover-chip"></div>
    </div>
    <div class="tabs" id="tabs">
      <button data-route="overview">Overview</button>
      <button data-route="regions">Regions</button>
      <button data-route="county">County Detail</button>
    </div>
  </div>

  <div class="downloads">
    <a href="pa_housing_summary.csv" download>&darr; Summary CSV</a>
    <a href="pa_housing_monthly.csv" download>&darr; Monthly CSV</a>
  </div>

  <div id="view-overview" class="view">
    <div class="filters">
      <label for="f-momentum">Momentum</label>
      <select id="f-momentum">
        <option value="all">All</option>
        <option value="hot">Hot (&ge;5% YoY)</option>
        <option value="steady">Steady (0&ndash;5%)</option>
        <option value="cooling">Cooling (&lt;0%)</option>
      </select>
      <label for="f-flag">Flags</label>
      <select id="f-flag">
        <option value="all">All</option>
        <option value="flagged">Flagged only</option>
        <option value="clean">Clean only</option>
      </select>
      <label for="f-pa-region">Region</label>
      <select id="f-pa-region"></select>
    </div>

    <div class="kpis" id="kpis"></div>

    <div class="charts">
      <div class="card">
        <h3>Consistency Test: 1-Year vs 5-Year Growth</h3>
        <div class="hint">Each county's short-term move tested against its long-term trajectory. Click a point to open its County Detail.</div>
        <canvas id="scatter"></canvas>
      </div>
      <div class="card">
        <h3>Top 15 by YoY Growth</h3>
        <div class="hint">Teal = consistent, amber/red = flagged by exception tests. Click a bar to open its County Detail.</div>
        <canvas id="bars"></canvas>
      </div>
    </div>

    <div class="card spaced" id="trend-card">
      <h3>Value Trend <select id="f-region" style="margin-left:8px;font-size:13px;padding:3px 6px"></select></h3>
      <div class="hint">Quarterly typical home value, last 10 years. Verify flagged counties here: is the spike one odd quarter or a sustained ramp?</div>
      <canvas id="trend" style="max-height:280px"></canvas>
    </div>

    <div class="card spaced">
      <h3>Exception Report</h3>
      <div class="hint">Automated tests applied to every county. A flag is not a verdict &mdash; it's a work item.</div>
      <div id="anomaly-list"></div>
    </div>

    <div class="card">
      <h3>County Detail</h3>
      <div class="hint">Click any header to sort. Data bars scale within column. Click a county name to open its detail page.</div>
      <div class="tbl-wrap"><table id="tbl">
        <thead><tr>
          <th data-k="flagSort">Flag</th><th data-k="region">County</th>
          <th data-k="pa_region">Region</th>
          <th data-k="latest_zhvi">Typical Value</th><th data-k="yoy_pct">YoY %</th>
          <th data-k="growth_5yr_pct">5-Yr %</th><th data-k="implied_prior4yr">Implied Prior 4-Yr %</th>
          <th data-k="yoy_rank">YoY Rank</th>
        </tr></thead><tbody></tbody>
      </table></div>
    </div>
  </div>

  <div id="view-regions" class="view">
    <div class="region-cards" id="region-cards"></div>
    <div class="card spaced">
      <h3>Regional Comparison &mdash; Avg YoY Growth</h3>
      <div class="hint">Click a card above to filter the Overview to that region.</div>
      <canvas id="region-bar"></canvas>
    </div>
  </div>

  <div id="view-county" class="view">
    <div class="county-picker-row">
      <button id="county-prev">&larr; Prev</button>
      <select id="county-picker"></select>
      <button id="county-next">Next &rarr;</button>
    </div>
    <div id="county-content"></div>
  </div>

  <div class="ftr"><strong>Methodology &amp; data-quality notes:</strong>
  ZHVI is a smoothed, seasonally-adjusted estimate of typical home value (35th&ndash;65th percentile), not a
  transaction average &mdash; treat it as an index, not an appraisal. &ldquo;Implied prior 4-yr %&rdquo; back-solves growth
  in years 2&ndash;5 given the 1-yr and 5-yr figures ((1+g&#8325;)/(1+g&#8321;)&minus;1); a large gap between the 1-yr rate
  and this baseline is the core consistency test. Rural counties have thin transaction volume, so small absolute
  moves produce large percentage swings &mdash; corroborate single-county figures against deed records.
  Source: Zillow Research public data via the data-platform pipeline. Generated automatically &mdash; do not edit by hand.</div>
</div>

<script>
const SUMMARY = __SUMMARY_JSON__;
const MONTHLY = __MONTHLY_JSON__;
const REGIONAL = __REGIONAL_JSON__;
const AMENITIES = __AMENITIES_JSON__;
const META = __META_JSON__;

document.getElementById("subline").textContent =
  `Zillow ZHVI · County level · Data through ${META.latest_date} · ${META.county_count} counties · Generated ${META.generated}`;

const ROWS = SUMMARY.map(r => ({...r,
  flagSort: r.flag_severity==="red"?0:r.flag_severity==="amber"?1:2,
  momentum: r.yoy_pct>=5?"hot":r.yoy_pct>=0?"steady":"cooling"}));

const REGION_ROWS = REGIONAL.summary;

const topMover = [...ROWS].sort((a,b)=>b.yoy_pct-a.yoy_pct)[0];
document.getElementById("top-mover-chip").innerHTML =
  `&uarr; Top mover: <strong>${topMover.region}</strong> ${topMover.yoy_pct.toFixed(1)}% YoY`;

const STATEWIDE = (()=>{
  const med=a=>{const s=[...a].sort((x,y)=>x-y);const m=s.length>>1;return s.length%2?s[m]:(s[m-1]+s[m])/2;};
  const avg=a=>a.reduce((s,x)=>s+x,0)/a.length;
  return {
    median_zhvi: med(ROWS.map(r=>r.latest_zhvi)),
    avg_yoy_pct: avg(ROWS.map(r=>r.yoy_pct)),
    avg_affordability_ratio: avg(ROWS.map(r=>r.affordability_ratio).filter(x=>x!=null)),
  };
})();

document.addEventListener("click", e => {
  const link = e.target.closest(".county-link");
  if (!link) return;
  e.preventDefault();
  location.hash = `county/${link.dataset.slug}`;
});

document.querySelectorAll("#tabs button").forEach(btn=>btn.onclick=()=>{
  const r=btn.dataset.route;
  location.hash = r==="county" ? `county/${lastCountySlug || ROWS[0].slug}` : r;
});

/* ---------- Overview: filters, KPIs, charts, table ---------- */

let state={momentum:"all",flag:"all",paRegion:"all",sortK:"yoy_rank",sortDir:1};
const visible=()=>ROWS.filter(r=>
  (state.momentum==="all"||r.momentum===state.momentum)&&
  (state.paRegion==="all"||r.pa_region===state.paRegion)&&
  (state.flag==="all"||(state.flag==="flagged"?r.flag_severity!=="none":r.flag_severity==="none")));
document.getElementById("f-momentum").onchange=e=>{state.momentum=e.target.value;renderAll();};
document.getElementById("f-flag").onchange=e=>{state.flag=e.target.value;renderAll();};
document.getElementById("f-pa-region").innerHTML = `<option value="all">All</option>` +
  REGION_ROWS.map(r=>`<option value="${r.pa_region}">${r.pa_region}</option>`).join("");
document.getElementById("f-pa-region").onchange=e=>{state.paRegion=e.target.value;renderAll();};

function renderKPIs(){
  const v=visible();
  const avg=a=>a.reduce((s,x)=>s+x,0)/(a.length||1);
  const flagged=v.filter(r=>r.flag_severity!=="none").length;
  const spread=v.length?Math.max(...v.map(r=>r.yoy_pct))-Math.min(...v.map(r=>r.yoy_pct)):0;
  const med=a=>{const s=[...a].sort((x,y)=>x-y);const m=s.length>>1;return s.length?(s.length%2?s[m]:(s[m-1]+s[m])/2):0;};
  document.getElementById("kpis").innerHTML=`
    <div class="kpi"><div class="lbl">Counties Shown</div><div class="val">${v.length}</div><div class="note">of ${META.county_count} total</div></div>
    <div class="kpi"><div class="lbl">Median Value</div><div class="val">$${Math.round(med(v.map(r=>r.latest_zhvi))/1000)}K</div><div class="note">typical home, shown counties</div></div>
    <div class="kpi"><div class="lbl">Avg YoY Growth</div><div class="val">${avg(v.map(r=>r.yoy_pct)).toFixed(1)}%</div><div class="note">unweighted mean</div></div>
    <div class="kpi"><div class="lbl">YoY Spread</div><div class="val">${spread.toFixed(1)}pts</div><div class="note">max &minus; min; dispersion check</div></div>
    <div class="kpi ${flagged?"flagged":""}"><div class="lbl">Counties Flagged</div><div class="val">${flagged}</div><div class="note">exception tests below</div></div>`;
}

const sevColor=r=>r.flag_severity==="red"?"#c0392b":r.flag_severity==="amber"?"#b7791f":"#0e7c7b";
let scatterChart,barChart,trendChart;

function renderCharts(){
  const v=visible();
  scatterChart?.destroy();barChart?.destroy();
  scatterChart=new Chart(document.getElementById("scatter"),{type:"scatter",
    data:{datasets:[{data:v.map(r=>({x:r.growth_5yr_pct,y:r.yoy_pct,region:r.region,slug:r.slug})),
      backgroundColor:v.map(sevColor),pointRadius:5,pointHoverRadius:8}]},
    options:{responsive:true,onClick:(evt,els)=>{if(els.length) location.hash=`county/${v[els[0].index].slug}`;},
      plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>`${c.raw.region}: ${c.raw.y}% YoY, ${c.raw.x}% 5-yr`}}},
      scales:{x:{title:{display:true,text:"5-Year Growth %"},grid:{color:"#eef0f3"}},
              y:{title:{display:true,text:"YoY Growth %"},grid:{color:"#eef0f3"}}}}});
  const top=[...v].sort((a,b)=>b.yoy_pct-a.yoy_pct).slice(0,15);
  barChart=new Chart(document.getElementById("bars"),{type:"bar",
    data:{labels:top.map(r=>r.region.replace(" County","")),
      datasets:[{data:top.map(r=>r.yoy_pct),backgroundColor:top.map(sevColor),borderRadius:3}]},
    options:{indexAxis:"y",responsive:true,onClick:(evt,els)=>{if(els.length) location.hash=`county/${top[els[0].index].slug}`;},
      plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` ${c.parsed.x}% YoY`}}},
      scales:{x:{title:{display:true,text:"YoY %"},grid:{color:"#eef0f3"}},y:{grid:{display:false}}}}});
}

function renderTrend(){
  const sel=document.getElementById("f-region");
  const series=MONTHLY[sel.value]||[];
  trendChart?.destroy();
  trendChart=new Chart(document.getElementById("trend"),{type:"line",
    data:{labels:series.map(p=>p.d),
      datasets:[{data:series.map(p=>p.v),borderColor:"#0e7c7b",backgroundColor:"rgba(14,124,123,.12)",
        borderWidth:2,fill:true,tension:.3,pointRadius:0,pointHoverRadius:5}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` $${c.parsed.y.toLocaleString()}`}}},
      scales:{x:{grid:{display:false},ticks:{maxTicksLimit:10}},
              y:{grid:{color:"#eef0f3"},ticks:{callback:v=>"$"+Math.round(v/1000)+"K"}}}}});
}

function initTrendSelect(){
  const sel=document.getElementById("f-region");
  const flaggedFirst=[...ROWS].sort((a,b)=>a.flagSort-b.flagSort||a.region.localeCompare(b.region));
  sel.innerHTML=flaggedFirst.map(r=>{
    const mark=r.flag_severity!=="none"?" ⚠":"";
    return `<option value="${r.region}">${r.region}${mark}</option>`;}).join("");
  sel.onchange=renderTrend;
}

function renderAnomalies(){
  const items=visible().filter(r=>r.flag_severity!=="none");
  const el=document.getElementById("anomaly-list");
  if(!items.length){el.innerHTML=`<div class="anomaly"><span class="badge grey">CLEAN</span><div>No exceptions under current filters.</div></div>`;return;}
  el.innerHTML=items.map(r=>
    `<div class="anomaly"><span class="badge ${r.flag_severity==="red"?"red":"amber"}">${r.flag_severity.toUpperCase()}</span>
     <div><strong><a href="#county/${r.slug}" class="county-link" data-slug="${r.slug}">${r.region}</a> &mdash; ${r.flag_test}:</strong> ${r.flag_detail}</div></div>`).join("");
}

function renderTable(){
  const v=[...visible()].sort((a,b)=>{const x=a[state.sortK],y=b[state.sortK];
    return (x>y?1:x<y?-1:0)*state.sortDir;});
  const maxY=Math.max(...ROWS.map(r=>Math.abs(r.yoy_pct)));
  const max5=Math.max(...ROWS.map(r=>Math.abs(r.growth_5yr_pct)));
  document.querySelector("#tbl tbody").innerHTML=v.map(r=>`<tr>
    <td><span class="flag-dot ${r.flag_severity==="none"?"none":r.flag_severity}"></span>${r.flag_test||"—"}</td>
    <td><a href="#county/${r.slug}" class="county-link" data-slug="${r.slug}">${r.region}</a></td>
    <td>${r.pa_region}</td>
    <td>$${r.latest_zhvi.toLocaleString()}</td>
    <td class="bar-cell"><div class="bar" style="width:${Math.abs(r.yoy_pct)/maxY*100}%"></div><span>${r.yoy_pct.toFixed(1)}%</span></td>
    <td class="bar-cell"><div class="bar ${r.growth_5yr_pct<0?"negbar":""}" style="width:${Math.abs(r.growth_5yr_pct)/max5*100}%"></div><span>${r.growth_5yr_pct.toFixed(1)}%</span></td>
    <td>${r.implied_prior4yr.toFixed(1)}%</td>
    <td>${r.yoy_rank}</td></tr>`).join("");
}
document.querySelectorAll("#tbl thead th").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;state.sortDir=state.sortK===k?-state.sortDir:1;state.sortK=k;renderTable();});

function renderAll(){renderKPIs();renderCharts();renderAnomalies();renderTable();}

/* ---------- Regions view ---------- */

let regionBarChart;
const sparkCharts={};

function renderRegions(){
  const el=document.getElementById("region-cards");
  el.innerHTML=REGION_ROWS.map(r=>`
    <div class="region-card" data-region="${r.pa_region}">
      <h4>${r.pa_region}</h4>
      <div class="rc-stats">
        <div><strong>$${Math.round(r.median_zhvi/1000)}K</strong>median value</div>
        <div><strong>${r.avg_yoy_pct.toFixed(1)}%</strong>avg YoY</div>
        <div><strong>${r.avg_affordability_ratio!=null?r.avg_affordability_ratio.toFixed(1)+"x":"n/a"}</strong>affordability</div>
        <div><strong>${r.flagged_count}</strong>flagged / ${r.county_count}</div>
        <div><strong>${r.amenities_per_10k.toFixed(1)}</strong>amenities /10k residents</div>
      </div>
      <canvas id="spark-${r.slug}"></canvas>
    </div>`).join("");

  el.querySelectorAll(".region-card").forEach(card=>card.onclick=()=>{
    state.paRegion=card.dataset.region;
    document.getElementById("f-pa-region").value=card.dataset.region;
    location.hash="overview";
  });

  Object.values(sparkCharts).forEach(c=>c.destroy());
  REGION_ROWS.forEach(r=>{
    const series=REGIONAL.monthly[r.pa_region]||[];
    sparkCharts[r.pa_region]=new Chart(document.getElementById(`spark-${r.slug}`),{type:"line",
      data:{labels:series.map(p=>p.d),datasets:[{data:series.map(p=>p.v),borderColor:"#0e7c7b",
        borderWidth:1.5,pointRadius:0,tension:.3,fill:false}]},
      options:{responsive:true,animation:false,
        plugins:{legend:{display:false},tooltip:{enabled:false}},
        scales:{x:{display:false},y:{display:false}}}});
  });

  regionBarChart?.destroy();
  const sorted=[...REGION_ROWS].sort((a,b)=>b.avg_yoy_pct-a.avg_yoy_pct);
  regionBarChart=new Chart(document.getElementById("region-bar"),{type:"bar",
    data:{labels:sorted.map(r=>r.pa_region),
      datasets:[{data:sorted.map(r=>r.avg_yoy_pct),backgroundColor:"#0e7c7b",borderRadius:3}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` ${c.parsed.y}% avg YoY`}}},
      scales:{x:{grid:{display:false},ticks:{autoSkip:false,maxRotation:30}},
              y:{title:{display:true,text:"Avg YoY %"},grid:{color:"#eef0f3"}}}}});
}

/* ---------- County Detail view ---------- */

let countyTrendChart, countyValueChart, countyAffordChart;
let lastCountySlug=null;

function initCountyPicker(){
  const sel=document.getElementById("county-picker");
  const sorted=[...ROWS].sort((a,b)=>a.region.localeCompare(b.region));
  sel.innerHTML=sorted.map(r=>`<option value="${r.slug}">${r.region} (${r.pa_region})</option>`).join("");
  sel.onchange=e=>{location.hash=`county/${e.target.value}`;};
  document.getElementById("county-prev").onclick=()=>navigatePeer(-1);
  document.getElementById("county-next").onclick=()=>navigatePeer(1);
}

function regionPeers(row){
  return ROWS.filter(r=>r.pa_region===row.pa_region).sort((a,b)=>a.region.localeCompare(b.region));
}

const AMENITY_GROUPS = [
  ["Parks", "park", null],
  ["Golf Courses", "golf_course", null],
  ["Playgrounds", "playground", null],
  ["Baseball Pitches", "pitch", "baseball"],
  ["Soccer Pitches", "pitch", "soccer"],
  ["Rugby Pitches", "pitch", "rugby"],
  ["Basketball Pitches", "pitch", "basketball"],
  ["Tennis Pitches", "pitch", "tennis"],
];

function amenityDetailsBlock(label, category, sport, countyAmenities){
  const items=countyAmenities.filter(a=>a.category===category && (sport?a.sport===sport:true));
  const body=items.length
    ? `<ul>${items.map(a=>`<li>${a.name||"(unnamed)"}</li>`).join("")}</ul>`
    : `<div class="hint">None found nearby.</div>`;
  return `<details class="amenity-group">
    <summary>${label} <span class="amenity-count">${items.length}</span></summary>
    ${body}
  </details>`;
}

function navigatePeer(delta){
  const row=ROWS.find(r=>r.slug===lastCountySlug);
  if(!row) return;
  const peers=regionPeers(row);
  const idx=peers.findIndex(r=>r.slug===row.slug)+delta;
  if(idx>=0 && idx<peers.length) location.hash=`county/${peers[idx].slug}`;
}

function renderCounty(slug){
  const row=ROWS.find(r=>r.slug===slug) || ROWS[0];
  lastCountySlug=row.slug;
  document.getElementById("county-picker").value=row.slug;

  const peers=regionPeers(row);
  const idx=peers.findIndex(r=>r.slug===row.slug);
  document.getElementById("county-prev").disabled = idx<=0;
  document.getElementById("county-next").disabled = idx>=peers.length-1;

  const regional=REGION_ROWS.find(r=>r.pa_region===row.pa_region);
  const flagBlock = row.flag_severity==="none"
    ? `<div class="anomaly"><span class="badge grey">CLEAN</span><div>No exceptions &mdash; figures internally consistent.</div></div>`
    : `<div class="anomaly"><span class="badge ${row.flag_severity==="red"?"red":"amber"}">${row.flag_severity.toUpperCase()}</span>
       <div><strong>${row.flag_test}:</strong> ${row.flag_detail}</div></div>`;

  document.getElementById("county-content").innerHTML = `
    <div class="region-context">Part of the <strong>${row.pa_region}</strong> region &mdash;
      ${regional.county_count} counties tracked, ${regional.flagged_count} flagged.</div>

    <div class="kpis">
      <div class="kpi"><div class="lbl">Typical Value</div><div class="val">$${row.latest_zhvi.toLocaleString()}</div><div class="note">latest ZHVI</div></div>
      <div class="kpi"><div class="lbl">YoY Growth</div><div class="val">${row.yoy_pct.toFixed(1)}%</div><div class="note">${row.momentum}</div></div>
      <div class="kpi"><div class="lbl">5-Yr Growth</div><div class="val">${row.growth_5yr_pct.toFixed(1)}%</div><div class="note">implied prior 4-yr ${row.implied_prior4yr.toFixed(1)}%</div></div>
      <div class="kpi"><div class="lbl">YoY Rank</div><div class="val">#${row.yoy_rank}</div><div class="note">of ${META.county_count} counties</div></div>
      <div class="kpi"><div class="lbl">Affordability</div><div class="val">${row.affordability_ratio!=null?row.affordability_ratio.toFixed(1)+"x":"n/a"}</div><div class="note">value &divide; median income</div></div>
    </div>

    <div class="card spaced">
      <h3>${row.region} &mdash; Demographics</h3>
      <div class="tbl-wrap"><table class="demo-tbl"><thead><tr>
        <th>Population</th><th>Median Income</th><th>Median Age</th><th>Owner-Occupancy</th>
      </tr></thead><tbody><tr>
        <td>${row.population!=null?row.population.toLocaleString():"n/a"}</td>
        <td>${row.median_income!=null?"$"+row.median_income.toLocaleString():"n/a"}</td>
        <td>${row.median_age!=null?row.median_age:"n/a"}</td>
        <td>${row.owner_occupancy_pct!=null?row.owner_occupancy_pct+"%":"n/a"}</td>
      </tr></tbody></table></div>
    </div>

    <div class="card spaced">
      <h3>Living Here &mdash; Schools</h3>
      <div class="kpis">
        <div class="kpi"><div class="lbl">School Districts</div><div class="val">${row.district_count}</div><div class="note">regular public districts</div></div>
        <div class="kpi"><div class="lbl">Public Enrollment</div><div class="val">${row.total_enrollment.toLocaleString()}</div><div class="note">all public LEAs</div></div>
        <div class="kpi"><div class="lbl">Private Schools</div><div class="val">${row.private_school_count}</div><div class="note">NCES PSS count</div></div>
      </div>
    </div>

    <div class="card spaced">
      <h3>Living Here &mdash; Amenities</h3>
      <div class="hint">${row.total_amenities} total recreational amenities nearby. Amenities data as of ${META.amenities_as_of} (OpenStreetMap). Click a category to see names.</div>
      <div class="amenity-groups">${AMENITY_GROUPS.map(([label,cat,sport])=>
        amenityDetailsBlock(label, cat, sport, AMENITIES[row.region]||[])).join("")}</div>
    </div>

    <div class="card spaced">
      <h3>Value Trend</h3>
      <div class="hint">Quarterly typical home value, last 10 years.</div>
      <canvas id="county-trend" style="max-height:280px"></canvas>
    </div>

    <div class="bench-grid">
      <div class="card">
        <h3>Typical Value vs Benchmarks</h3>
        <canvas id="county-bench-value"></canvas>
        <div class="hint">This County $${row.latest_zhvi.toLocaleString()} &middot;
          Region Avg $${Math.round(regional.median_zhvi).toLocaleString()} &middot;
          Statewide $${Math.round(STATEWIDE.median_zhvi).toLocaleString()}</div>
      </div>
      <div class="card">
        <h3>Affordability vs Benchmarks</h3>
        <canvas id="county-bench-afford"></canvas>
        <div class="hint">This County ${row.affordability_ratio!=null?row.affordability_ratio.toFixed(1)+"x":"n/a"} &middot;
          Region Avg ${regional.avg_affordability_ratio!=null?regional.avg_affordability_ratio.toFixed(1)+"x":"n/a"} &middot;
          Statewide ${STATEWIDE.avg_affordability_ratio.toFixed(1)}x</div>
      </div>
    </div>

    <div class="card">
      <h3>Forensic Status</h3>
      <div id="county-flag">${flagBlock}</div>
    </div>`;

  const series=MONTHLY[row.region]||[];
  countyTrendChart?.destroy();
  countyTrendChart=new Chart(document.getElementById("county-trend"),{type:"line",
    data:{labels:series.map(p=>p.d),datasets:[{data:series.map(p=>p.v),borderColor:"#0e7c7b",
      backgroundColor:"rgba(14,124,123,.12)",borderWidth:2,fill:true,tension:.3,pointRadius:0,pointHoverRadius:5}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` $${c.parsed.y.toLocaleString()}`}}},
      scales:{x:{grid:{display:false},ticks:{maxTicksLimit:10}},
              y:{grid:{color:"#eef0f3"},ticks:{callback:v=>"$"+Math.round(v/1000)+"K"}}}}});

  countyValueChart?.destroy();
  countyValueChart=new Chart(document.getElementById("county-bench-value"),{type:"bar",
    data:{labels:["This County","Region Avg","Statewide"],
      datasets:[{data:[row.latest_zhvi, regional.median_zhvi, STATEWIDE.median_zhvi],
        backgroundColor:["#0e7c7b","#6b7280","#1b2a41"],borderRadius:3}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` $${c.parsed.y.toLocaleString()}`}}},
      scales:{y:{ticks:{callback:v=>"$"+Math.round(v/1000)+"K"},grid:{color:"#eef0f3"}},x:{grid:{display:false}}}}});

  countyAffordChart?.destroy();
  countyAffordChart=new Chart(document.getElementById("county-bench-afford"),{type:"bar",
    data:{labels:["This County","Region Avg","Statewide"],
      datasets:[{data:[row.affordability_ratio, regional.avg_affordability_ratio, STATEWIDE.avg_affordability_ratio],
        backgroundColor:["#0e7c7b","#6b7280","#1b2a41"],borderRadius:3}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>` ${c.parsed.y.toFixed(1)}x`}}},
      scales:{y:{ticks:{callback:v=>v+"x"},grid:{color:"#eef0f3"}},x:{grid:{display:false}}}}});
}

/* ---------- Hash router ---------- */

function parseRoute(){
  const raw=(location.hash||"").replace(/^#\/?/, "");
  if(raw.startsWith("county/")) return {view:"county", slug:decodeURIComponent(raw.slice(7))};
  if(raw==="regions") return {view:"regions", slug:null};
  return {view:"overview", slug:null};
}

function showView(view){
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  document.getElementById(`view-${view}`).classList.add("active");
  document.querySelectorAll("#tabs button").forEach(b=>b.classList.toggle("active", b.dataset.route===view));
}

function route(){
  const {view, slug}=parseRoute();
  showView(view);
  if(view==="overview"){ renderAll(); renderTrend(); }
  else if(view==="regions"){ renderRegions(); }
  else if(view==="county"){ renderCounty(slug || lastCountySlug || ROWS[0].slug); }
  window.scrollTo(0,0);
}

window.addEventListener("hashchange", route);
initTrendSelect();
initCountyPicker();
route();
</script>
</body>
</html>
"""
