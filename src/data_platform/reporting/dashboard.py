"""Render the PA Housing dashboard as a self-contained HTML file.

The pipeline calls build_dashboard() after writing its CSVs; the output at
reports/pa_housing_dashboard.html opens in any browser with no dependencies.
All data is embedded as JSON; forensic flags come from reporting.forensic.
"""

import json
import logging
from datetime import date
from pathlib import Path

import pandas as pd

from data_platform.reporting.forensic import run_forensic_tests

logger = logging.getLogger(__name__)

TREND_YEARS = 10  # embed this many years of history, quarterly


def _monthly_to_quarterly(monthly: pd.DataFrame) -> dict[str, list]:
    """Pre-aggregate monthly rows to quarterly means per region (keeps HTML small)."""
    df = monthly.copy()
    df["date"] = pd.to_datetime(df["date"])
    cutoff = df["date"].max() - pd.DateOffset(years=TREND_YEARS)
    df = df[df["date"] >= cutoff]
    df["quarter"] = df["date"].dt.to_period("Q").dt.to_timestamp()
    q = df.groupby(["region", "quarter"], as_index=False)["zhvi"].mean()
    out: dict[str, list] = {}
    for region, grp in q.groupby("region"):
        out[region] = [
            {"d": ts.strftime("%Y-%m"), "v": round(v)}
            for ts, v in zip(grp["quarter"], grp["zhvi"], strict=True)
        ]
    return out


def build_dashboard(
    summary: pd.DataFrame,
    monthly: pd.DataFrame,
    out_path: Path = Path("reports/pa_housing_dashboard.html"),
) -> Path:
    tested = run_forensic_tests(summary)
    tested["latest_date"] = tested["latest_date"].astype(str)
    records = tested.astype(object).where(tested.notna(), None).to_dict(orient="records")
    meta = {
        "generated": date.today().isoformat(),
        "latest_date": str(summary["latest_date"].iloc[0]),
        "county_count": int(len(summary)),
    }
    html = (
        _TEMPLATE.replace("__SUMMARY_JSON__", json.dumps(records))
        .replace("__MONTHLY_JSON__", json.dumps(_monthly_to_quarterly(monthly)))
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
.filters{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.filters label{font-size:12px;opacity:.75}
.filters select{padding:6px 10px;border:1px solid rgba(255,255,255,.25);border-radius:5px;
background:rgba(255,255,255,.1);color:var(--on-dark);font-size:13px}
.filters select option{background:var(--bg-header)}
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
@media(max-width:820px){.charts{grid-template-columns:1fr}}
</style>
</head>
<body>
<div class="wrap">
  <div class="hdr">
    <div>
      <h1>PA Housing Market Tracker</h1>
      <div class="sub" id="subline"></div>
    </div>
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
    </div>
  </div>

  <div class="kpis" id="kpis"></div>

  <div class="charts">
    <div class="card">
      <h3>Consistency Test: 1-Year vs 5-Year Growth</h3>
      <div class="hint">Each county's short-term move tested against its long-term trajectory. Points far off the pack need verification before use.</div>
      <canvas id="scatter"></canvas>
    </div>
    <div class="card">
      <h3>Top 15 by YoY Growth</h3>
      <div class="hint">Teal = consistent, amber/red = flagged by exception tests.</div>
      <canvas id="bars"></canvas>
    </div>
  </div>

  <div class="card spaced">
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
    <div class="hint">Click any header to sort. Data bars scale within column.</div>
    <div class="tbl-wrap"><table id="tbl">
      <thead><tr>
        <th data-k="flagSort">Flag</th><th data-k="region">County</th>
        <th data-k="latest_zhvi">Typical Value</th><th data-k="yoy_pct">YoY %</th>
        <th data-k="growth_5yr_pct">5-Yr %</th><th data-k="implied_prior4yr">Implied Prior 4-Yr %</th>
        <th data-k="yoy_rank">YoY Rank</th>
      </tr></thead><tbody></tbody>
    </table></div>
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
const META = __META_JSON__;

document.getElementById("subline").textContent =
  `Zillow ZHVI · County level · Data through ${META.latest_date} · ${META.county_count} counties · Generated ${META.generated}`;

const ROWS = SUMMARY.map(r => ({...r,
  flagSort: r.flag_severity==="red"?0:r.flag_severity==="amber"?1:2,
  momentum: r.yoy_pct>=5?"hot":r.yoy_pct>=0?"steady":"cooling"}));

let state={momentum:"all",flag:"all",sortK:"yoy_rank",sortDir:1};
const visible=()=>ROWS.filter(r=>
  (state.momentum==="all"||r.momentum===state.momentum)&&
  (state.flag==="all"||(state.flag==="flagged"?r.flag_severity!=="none":r.flag_severity==="none")));
document.getElementById("f-momentum").onchange=e=>{state.momentum=e.target.value;renderAll();};
document.getElementById("f-flag").onchange=e=>{state.flag=e.target.value;renderAll();};

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
    data:{datasets:[{data:v.map(r=>({x:r.growth_5yr_pct,y:r.yoy_pct,region:r.region})),
      backgroundColor:v.map(sevColor),pointRadius:5,pointHoverRadius:8}]},
    options:{responsive:true,plugins:{legend:{display:false},
      tooltip:{callbacks:{label:c=>`${c.raw.region}: ${c.raw.y}% YoY, ${c.raw.x}% 5-yr`}}},
      scales:{x:{title:{display:true,text:"5-Year Growth %"},grid:{color:"#eef0f3"}},
              y:{title:{display:true,text:"YoY Growth %"},grid:{color:"#eef0f3"}}}}});
  const top=[...v].sort((a,b)=>b.yoy_pct-a.yoy_pct).slice(0,15);
  barChart=new Chart(document.getElementById("bars"),{type:"bar",
    data:{labels:top.map(r=>r.region.replace(" County","")),
      datasets:[{data:top.map(r=>r.yoy_pct),backgroundColor:top.map(sevColor),borderRadius:3}]},
    options:{indexAxis:"y",responsive:true,plugins:{legend:{display:false},
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
    const mark=r.flag_severity!=="none"?" \u26A0":"";
    return `<option value="${r.region}">${r.region}${mark}</option>`;}).join("");
  sel.onchange=renderTrend;
}

function renderAnomalies(){
  const items=visible().filter(r=>r.flag_severity!=="none");
  const el=document.getElementById("anomaly-list");
  if(!items.length){el.innerHTML=`<div class="anomaly"><span class="badge grey">CLEAN</span><div>No exceptions under current filters.</div></div>`;return;}
  el.innerHTML=items.map(r=>
    `<div class="anomaly"><span class="badge ${r.flag_severity==="red"?"red":"amber"}">${r.flag_severity.toUpperCase()}</span>
     <div><strong>${r.region} &mdash; ${r.flag_test}:</strong> ${r.flag_detail}</div></div>`).join("");
}

function renderTable(){
  const v=[...visible()].sort((a,b)=>{const x=a[state.sortK],y=b[state.sortK];
    return (x>y?1:x<y?-1:0)*state.sortDir;});
  const maxY=Math.max(...ROWS.map(r=>Math.abs(r.yoy_pct)));
  const max5=Math.max(...ROWS.map(r=>Math.abs(r.growth_5yr_pct)));
  document.querySelector("#tbl tbody").innerHTML=v.map(r=>`<tr>
    <td><span class="flag-dot ${r.flag_severity==="none"?"none":r.flag_severity}"></span>${r.flag_test||"\u2014"}</td>
    <td>${r.region}</td>
    <td>$${r.latest_zhvi.toLocaleString()}</td>
    <td class="bar-cell"><div class="bar" style="width:${Math.abs(r.yoy_pct)/maxY*100}%"></div><span>${r.yoy_pct.toFixed(1)}%</span></td>
    <td class="bar-cell"><div class="bar ${r.growth_5yr_pct<0?"negbar":""}" style="width:${Math.abs(r.growth_5yr_pct)/max5*100}%"></div><span>${r.growth_5yr_pct.toFixed(1)}%</span></td>
    <td>${r.implied_prior4yr.toFixed(1)}%</td>
    <td>${r.yoy_rank}</td></tr>`).join("");
}
document.querySelectorAll("#tbl thead th").forEach(th=>th.onclick=()=>{
  const k=th.dataset.k;state.sortDir=state.sortK===k?-state.sortDir:1;state.sortK=k;renderTable();});

function renderAll(){renderKPIs();renderCharts();renderAnomalies();renderTable();}
initTrendSelect();renderAll();renderTrend();
</script>
</body>
</html>
"""
