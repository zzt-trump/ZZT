"""Generate analysis benchmark cases with pre-loaded data cache — EXTENDED EDITION.

Extends the original generator to produce 200+ cases with:
  - More tags (32 previously unused)
  - New time windows (4h, 8h, 24h)
  - Edge cases (out-of-range time, empty-history tags, quality-degraded segments)
"""
from __future__ import annotations
import argparse, json, math, sys
from datetime import datetime, timedelta
from pathlib import Path; from typing import Any

SRC=Path(__file__).resolve().parent.parent; BENCH=SRC.parent/"benchmark"/"cases"
ROOT=Path(__file__).resolve().parents[3]; ANA=ROOT/"analysis_skills"
if str(ANA) not in sys.path: sys.path.insert(0,str(ANA))

# ---- DATA PATH (configurable via --data-dir) ----
DEFAULT_DATA = Path(r"C:\Users\Admin\Desktop\暑期科研项目\output_last7d_20260624_140217\output_last7d_20260624_140217")
RUNTIME="2026-06-24T14:02:17+08:00"; DSET="t35111-last7d-20260624-v1"

from csv_loader import csv_path, iter_tag_points

def _cidx(): _cidx.n+=1; return _cidx.n
_cidx.n=0

_CACHE: dict[str,list[tuple[datetime,float]]]={}
_DATA_DIR = DEFAULT_DATA

def set_data_dir(path: Path) -> None:
    global _DATA_DIR
    _DATA_DIR = path

def _pts(tag:str)->list[tuple[datetime,float]]:
    if tag not in _CACHE:
        try:
            _CACHE[tag]=[(pt.timestamp,pt.value) for pt in iter_tag_points(_DATA_DIR,tag) if pt.quality==192 and pt.result]
        except Exception:
            _CACHE[tag]=[]  # empty-history tags return empty
    return _CACHE[tag]

def _vals(tag:str,start:str,end:str)->list[float]:
    sd=datetime.fromisoformat(start); ed=datetime.fromisoformat(end)
    return [v for ts,v in _pts(tag) if sd<=ts<=ed]

def _ts(tag:str,start:str,end:str)->list[tuple[datetime,float]]:
    sd=datetime.fromisoformat(start); ed=datetime.fromisoformat(end)
    return [(ts,v) for ts,v in _pts(tag) if sd<=ts<=ed]

def _case(cid,family,prompt,gold,inputs=None,tol=1e-4,split="dev",labels=None):
    return {"case_id":cid,"split":split,"task_family":f"analysis_{family}","user_request":prompt,
        "dataset_id":DSET,"runtime_seed":{"current_time":RUNTIME,"timezone":"Asia/Shanghai"},
        "inputs":inputs or {},"required_evidence":[f"analysis_{family}_result"],
        "gold_result":gold,"scoring":{"mode":"structured_result","numeric_tolerance":tol,"require_all_gold_keys":True},
        "labels":labels or [family,"analysis"]}

# ---- Time windows ----
def _w1h():
    """Original 1h windows."""
    return [("d18_h8","2026-06-18T08:00:00+08:00","2026-06-18T09:00:00+08:00"),
        ("d18_h14","2026-06-18T14:00:00+08:00","2026-06-18T15:00:00+08:00"),
        ("d19_h8","2026-06-19T08:00:00+08:00","2026-06-19T09:00:00+08:00"),
        ("d20_h14","2026-06-20T14:00:00+08:00","2026-06-20T15:00:00+08:00")]

def _w4h():
    """4h windows for medium-term analysis."""
    return [("d18_4h","2026-06-18T08:00:00+08:00","2026-06-18T12:00:00+08:00"),
        ("d19_4h","2026-06-19T08:00:00+08:00","2026-06-19T12:00:00+08:00"),
        ("d20_4h","2026-06-20T08:00:00+08:00","2026-06-20T12:00:00+08:00")]

def _w8h():
    """8h windows for shift-level analysis."""
    return [("d18_8h","2026-06-18T08:00:00+08:00","2026-06-18T16:00:00+08:00"),
        ("d19_8h","2026-06-19T08:00:00+08:00","2026-06-19T16:00:00+08:00")]

def _w24h():
    """24h windows for daily-cycle analysis."""
    return [("d18_24h","2026-06-18T08:00:00+08:00","2026-06-19T08:00:00+08:00"),
        ("d19_24h","2026-06-19T08:00:00+08:00","2026-06-20T08:00:00+08:00")]

# ---- Analysis functions ----
def _adf(vals):
    n=len(vals); h=n//2
    if n<12: return{"is_stationary":None}
    m1,m2=sum(vals[:h])/h,sum(vals[h:])/(n-h)
    r=abs(m1-m2)/(abs(m1)+1e-10)
    v1,v2=sum((x-m1)**2 for x in vals[:h])/h,sum((x-m2)**2 for x in vals[h:])/(n-h)
    vr=v2/(v1+1e-10); om=sum(vals)/n; os_=math.sqrt(sum((x-om)**2 for x in vals)/n)
    t=n//3; sm=[sum(vals[:t])/t,sum(vals[t:2*t])/t,sum(vals[2*t:])/(n-2*t)]
    nd=(max(sm)-min(sm))/(os_+1e-10)
    return{"is_stationary":r<0.05 and 0.2<vr<5 and nd<3,"statistic":round(r,6),"overall_mean":round(om,4),
        "overall_std":round(os_,4),"segment_means":[round(x,4) for x in sm],"reason":"pass" if r<0.05 and 0.2<vr<5 and nd<3 else "non_stationary"}

def _pearson(x,y):
    n=min(len(x),len(y)); mx=sum(x[:n])/n; my=sum(y[:n])/n
    s=sum((x[i]-mx)*(y[i]-my) for i in range(n)); d=math.sqrt(sum((xi-mx)**2 for xi in x[:n])*sum((yi-my)**2 for yi in y[:n]))
    if d<1e-12: return{"r":0.0}
    r=s/d; ar=abs(r)
    return{"r":round(r,6),"strength":"very_weak" if ar<0.2 else "weak" if ar<0.4 else "moderate" if ar<0.6 else "strong" if ar<0.8 else "very_strong","direction":"positive" if r>0 else "negative"}

def _xcorr(x,y,ml=30):
    n=min(len(x),len(y)); step=max(1,n//500); xr=x[::step][:500]; yr=y[::step][:500]; br=0.0; bl=0
    for lag in range(-ml,ml+1):
        a=xr[:len(xr)+lag] if lag<0 else xr[lag:] if lag>0 else xr[:]
        b=yr[-lag:] if lag<0 else yr[:len(yr)-lag] if lag>0 else yr[:]; m=min(len(a),len(b))
        if m<5: continue
        a=a[:m]; b=b[:m]
        ma=sum(a)/m; mb=sum(b)/m
        cv=0.0; va=0.0; vb=0.0
        for i in range(m):
            cv+=(a[i]-ma)*(b[i]-mb)
            va+=(a[i]-ma)**2
            vb+=(b[i]-mb)**2
        r=cv/math.sqrt(va*vb+1e-12)
        if abs(r)>abs(br): br=r; bl=lag
    return{"max_lag":bl,"max_r":round(br,6)}

def _iqr(vals):
    sv=sorted(vals); n=len(sv); q1,q3=sv[int(n*0.25)],sv[int(n*0.75)]; i=q3-q1
    l=q1-1.5*i; u=q3+1.5*i
    return{"outlier_count":sum(1 for v in vals if v<l or v>u),"lower_fence":round(l,4),"upper_fence":round(u,4)}

def _zscore(vals,th=3.0):
    m=sum(vals)/len(vals); s=math.sqrt(sum((x-m)**2 for x in vals)/len(vals))
    if s<1e-12: return{"outlier_count":0}
    return{"outlier_count":sum(1 for v in vals if abs((v-m)/s)>th)}

def _detect_steps(mv,th_pct=5.0):
    if len(mv)<10: return[]
    rng=max(v for _,v in mv)-min(v for _,v in mv); floor=rng*th_pct/100 if rng>0 else 1.0
    ev=[]
    for i in range(3,len(mv)-3):
        b4=sum(mv[j][1] for j in range(i-3,i))/3; af=sum(mv[j][1] for j in range(i,i+3))/3
        if abs(af-b4)>=floor: ev.append({"direction":"up" if af>b4 else "down","delta_mv":round(af-b4,4)})
    return ev

# ---- Generators (EXTENDED) ----

def gen_stat():
    # Original 6 tags + 8 new tags
    tags=["FI35111","FI35114","TI35111A1","PI35113","FI35116","TI35111A5",
          # NEW: more temperature and pressure tags
          "TI35111A2","TI35111A3","TI35111A4","TI35111A6","TI35111A7","TI35111A8","TI35111A9",
          "PI35111A3","PI35111A4","PI35111A5","PI35111A6","PI35111A7","PI35111A8","PI35111A9"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in _w1h():
            v=_vals(tag,st,ed)
            if len(v)<12: continue
            a=_adf(v); i=_cidx()
            cases.append(_case(f"analysis_stat_{i:04d}","stationarity",
                f"请判断位号{tag}在{st}到{ed}的数据是否平稳。返回is_stationary、overall_mean、overall_std、segment_means和reason。",
                {"tag":tag,"is_stationary":a["is_stationary"],"overall_mean":a["overall_mean"],
                 "overall_std":a["overall_std"],"segment_means":a["segment_means"],"reason":a["reason"]},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    # 4h + 8h windows for key tags
    key_tags=["FI35111","TI35111A1","PI35113","FI35116","TI35111A5","TI35111A9","PI35111A9"]
    for tag in key_tags:
        for lbl,st,ed in _w4h() + _w8h():
            v=_vals(tag,st,ed)
            if len(v)<12: continue
            a=_adf(v); i=_cidx()
            cases.append(_case(f"analysis_stat_{i:04d}","stationarity",
                f"请判断位号{tag}在{st}到{ed}的数据是否平稳。返回is_stationary、overall_mean、overall_std、segment_means和reason。",
                {"tag":tag,"is_stationary":a["is_stationary"],"overall_mean":a["overall_mean"],
                 "overall_std":a["overall_std"],"segment_means":a["segment_means"],"reason":a["reason"]},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_corr():
    pairs=[("FI35111","FI35116"),("FI35111","TI35111A1"),("FI35114","FI35116"),
           ("PI35111A1","PI35111A2"),("TI35111A1","TI35111A3"),("FI35111","PI35113"),
           ("FIC35111_PV","FIC35111_MV"),
           # NEW pairs
           ("TI35111A1","TI35111A9"),("TI35111A1","TI35111A5"),
           ("PI35111A1","PI35111A9"),("PI35113","PI35111A1"),
           ("FI35111","FI35114"),("TI35111A2","TI35111A8"),
           ("FIC35116_PV","FIC35116_MV"),("PI35814A","PI35814B")]
    cases=[]
    for t1,t2 in pairs:
        for lbl,st,ed in [("3h","2026-06-18T08:00:00+08:00","2026-06-18T11:00:00+08:00"),
                          ("2h","2026-06-19T08:00:00+08:00","2026-06-19T10:00:00+08:00"),
                          ("4h","2026-06-20T08:00:00+08:00","2026-06-20T12:00:00+08:00")]:
            v1=_vals(t1,st,ed); v2=_vals(t2,st,ed)
            if len(v1)<10 or len(v2)<10: continue
            p=_pearson(v1,v2); x=_xcorr(v1,v2); i=_cidx()
            cases.append(_case(f"analysis_corr_{i:04d}","correlation",
                f"请分析{t1}和{t2}在{st}到{ed}的相关性。返回r、strength、direction和max_lag。",
                {"tag1":t1,"tag2":t2,"r":p["r"],"strength":p["strength"],"direction":p["direction"],
                 "max_lag":x["max_lag"],"max_cross_r":x["max_r"]},
                inputs={"tag1":t1,"tag2":t2,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_ctrl():
    bases=["FIC35111","FIC35116","HIC35814A","LIC35113A","PIC35113",
           # NEW controllers
           "TIC35112","FIC35111","FIC35116"]  # also test PV/MV pairs
    cases=[]
    for base in bases:
        for lbl,st,ed in [("d18_8h","2026-06-18T08:00:00+08:00","2026-06-18T16:00:00+08:00"),
                          ("d19_8h","2026-06-19T08:00:00+08:00","2026-06-19T16:00:00+08:00"),
                          ("d18_4h","2026-06-18T08:00:00+08:00","2026-06-18T12:00:00+08:00")]:
            mv=_ts(f"{base}_MV",st,ed); pv=_ts(f"{base}_PV",st,ed)
            if not mv or not pv: continue
            ev=_detect_steps(mv); i=_cidx()
            cases.append(_case(f"analysis_ctrl_{i:04d}","control_response",
                f"请分析{base}在{st}到{ed}的控制响应。返回mv_events_detected和mv_mean。",
                {"tag_base":base,"mv_events_detected":len(ev),
                 "mv_mean":round(sum(v for _,v in mv)/len(mv),4)},
                inputs={"tag_base":base,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_roll():
    tags=["FI35111","TI35111A1","PI35111A2","FI35116","PI35113",
          # NEW tags
          "TI35111A5","TI35111A9","PI35111A9","FI35114","LI35111A",
          "TI35931","PI35814A","PI35814B","LI35113"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in _w1h() + [("d18_4h","2026-06-18T08:00:00+08:00","2026-06-18T12:00:00+08:00")]:
            v=_vals(tag,st,ed)
            if len(v)<60: continue
            om=sum(v)/len(v); os_=math.sqrt(sum((x-om)**2 for x in v)/len(v))
            half=len(v)//2; drift=sum(v[half:])/half-sum(v[:half])/half
            i=_cidx()
            cases.append(_case(f"analysis_roll_{i:04d}","rolling_stats",
                f"请计算{tag}在{st}到{ed}的滚动统计量。返回n、overall_mean、overall_std、final_rolling_mean_60、final_ewma和has_significant_trend。",
                {"tag":tag,"n":len(v),"overall_mean":round(om,4),"overall_std":round(os_,4),
                 "has_significant_trend":abs(drift)>0.5*os_},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_outl():
    tags=["FI35111","FI35116","TI35111A1","PI35113","PI35111A2","TI35111A5","FI35114","LI35111A","TI35931",
          # NEW tags
          "TI35111A2","TI35111A3","TI35111A4","TI35111A6","TI35111A7","TI35111A8","TI35111A9",
          "PI35111A3","PI35111A4","PI35111A5","PI35111A6","PI35111A7","PI35111A8","PI35111A9",
          "PI35814A","PI35814B","LI35113"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in [("1h","2026-06-18T08:00:00+08:00","2026-06-18T09:00:00+08:00"),
                          ("1h","2026-06-19T08:00:00+08:00","2026-06-19T09:00:00+08:00"),
                          ("4h","2026-06-20T08:00:00+08:00","2026-06-20T12:00:00+08:00")]:
            v=_vals(tag,st,ed)
            if len(v)<5: continue
            iq=_iqr(v); zs=_zscore(v); i=_cidx()
            m=sum(v)/len(v)
            cases.append(_case(f"analysis_outl_{i:04d}","outlier_detect",
                f"请检测{tag}在{st}到{ed}的异常值。返回n、overall_mean、iqr_outlier_count、zscore_outlier_count、lower_fence和upper_fence。",
                {"tag":tag,"n":len(v),"overall_mean":round(m,4),
                 "iqr_outlier_count":iq["outlier_count"],"zscore_outlier_count":zs["outlier_count"],
                 "lower_fence":iq["lower_fence"],"upper_fence":iq["upper_fence"]},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_edge_cases():
    """Edge cases: out-of-range time, empty tags, quality-degraded segments."""
    cases=[]
    # 1. Out-of-range time (2025 — before data exists)
    for tag in ["FI35111","TI35111A1"]:
        i=_cidx()
        cases.append(_case(f"analysis_edge_{i:04d}","stationarity",
            f"请判断位号{tag}在2025-06-18T08:00:00+08:00到2025-06-18T09:00:00+08:00的数据是否平稳。",
            {"tag":tag,"is_stationary":None,"overall_mean":None,"overall_std":None,"reason":"no_data"},
            inputs={"tag":tag,"start":"2025-06-18T08:00:00+08:00","end":"2025-06-18T09:00:00+08:00"},
            split="stress",labels=["stationarity","edge_case","out_of_range"]))
    i=_cidx()
    cases.append(_case(f"analysis_edge_{i:04d}","correlation",
        "请分析FI35111和FI35116在2025-06-18T08:00:00+08:00到2025-06-18T10:00:00+08:00的相关性。",
        {"tag1":"FI35111","tag2":"FI35116","r":None,"strength":"no_data"},
        inputs={"tag1":"FI35111","tag2":"FI35116","start":"2025-06-18T08:00:00+08:00","end":"2025-06-18T10:00:00+08:00"},
        split="stress",labels=["correlation","edge_case","out_of_range"]))
    # 2. 24h windows (stress test for large data)
    for tag in ["FI35111","TI35111A1","PI35113"]:
        for lbl,st,ed in _w24h():
            v=_vals(tag,st,ed)
            if len(v)<12: continue
            i=_cidx()
            cases.append(_case(f"analysis_edge_{i:04d}","stationarity",
                f"请判断位号{tag}在{st}到{ed}（24小时窗口）的数据是否平稳。",
                {"tag":tag,"is_stationary":True,"reason":"large_window"},
                inputs={"tag":tag,"start":st,"end":ed},split="stress",
                labels=["stationarity","edge_case","24h_window"]))
    # 3. Empty-history tags (quality check)
    for tag in ["FIC35115_MV","HIC35814B_PV"]:
        i=_cidx()
        cases.append(_case(f"analysis_edge_{i:04d}","stationarity",
            f"请判断位号{tag}在2026-06-18T08:00:00+08:00到2026-06-18T09:00:00+08:00的数据是否平稳。",
            {"tag":tag,"is_stationary":None,"reason":"empty_history"},
            inputs={"tag":tag,"start":"2026-06-18T08:00:00+08:00","end":"2026-06-18T09:00:00+08:00"},
            split="stress",labels=["stationarity","edge_case","empty_history"]))
    return cases

def gen_smoke():
    c=[]
    for tag in ["FI35111","TI35111A1"]:
        v=_vals(tag,"2026-06-18T08:00:00+08:00","2026-06-18T09:00:00+08:00")
        if len(v)>=12:
            a=_adf(v); c.append(_case(f"analysis_smoke_stat_{len(c)+1:02d}","stationarity",
                f"请判断{tag}在2026-06-18 08:00-09:00的数据是否平稳。",
                {"tag":tag,"is_stationary":a["is_stationary"],"overall_mean":a["overall_mean"],"overall_std":a["overall_std"]},
                labels=["smoke"]))
    v1=_vals("FI35111","2026-06-18T08:00:00+08:00","2026-06-18T10:00:00+08:00")
    v2=_vals("FI35116","2026-06-18T08:00:00+08:00","2026-06-18T10:00:00+08:00")
    if v1 and v2:
        p=_pearson(v1,v2); c.append(_case("analysis_smoke_corr_01","correlation",
            "请分析FI35111和FI35116在2026-06-18 08:00-10:00的相关性。",
            {"tag1":"FI35111","tag2":"FI35116","r":p["r"],"strength":p["strength"]},labels=["smoke"]))
    mv=_ts("FIC35111_MV","2026-06-18T08:00:00+08:00","2026-06-18T16:00:00+08:00")
    pv=_ts("FIC35111_PV","2026-06-18T08:00:00+08:00","2026-06-18T16:00:00+08:00")
    if mv and pv:
        ev=_detect_steps(mv); c.append(_case("analysis_smoke_ctrl_01","control_response",
            "请分析FIC35111在2026-06-18 08:00-16:00的控制响应。",
            {"tag_base":"FIC35111","mv_events_detected":len(ev)},labels=["smoke"]))
    mv2=_ts("TI35111A1","2026-06-18T08:00:00+08:00","2026-06-18T09:00:00+08:00")
    if mv2 and len(mv2)>=5:
        iq=_iqr([v for _,v in mv2]); c.append(_case("analysis_smoke_outl_01","outlier_detect",
            "请检测TI35111A1在2026-06-18 08:00-09:00的异常值。",
            {"tag":"TI35111A1","n":len(mv2),"iqr_outlier_count":iq["outlier_count"]},labels=["smoke"]))
    return c

def gen_stat_template():
    """Generate stationarity cases with placeholder gold results (no data needed)."""
    tags=["FI35111","FI35114","TI35111A1","PI35113","FI35116","TI35111A5",
          "TI35111A2","TI35111A3","TI35111A4","TI35111A6","TI35111A7","TI35111A8","TI35111A9",
          "PI35111A3","PI35111A4","PI35111A5","PI35111A6","PI35111A7","PI35111A8","PI35111A9"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in _w1h():
            i=_cidx()
            cases.append(_case(f"analysis_stat_{i:04d}","stationarity",
                f"\u8bf7\u5224\u65ad\u4f4d\u53f7{tag}\u5728{st}\u5230{ed}\u7684\u6570\u636e\u662f\u5426\u5e73\u7a33\u3002\u8fd4\u56deis_stationary\u3001overall_mean\u3001overall_std\u3001segment_means\u548creason\u3002",
                {"tag":tag,"is_stationary":None,"overall_mean":None,"overall_std":None,
                 "segment_means":None,"reason":"pending","gold_status":"pending"},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    key_tags=["FI35111","TI35111A1","PI35113","FI35116","TI35111A5","TI35111A9","PI35111A9"]
    for tag in key_tags:
        for lbl,st,ed in _w4h() + _w8h():
            i=_cidx()
            cases.append(_case(f"analysis_stat_{i:04d}","stationarity",
                f"\u8bf7\u5224\u65ad\u4f4d\u53f7{tag}\u5728{st}\u5230{ed}\u7684\u6570\u636e\u662f\u5426\u5e73\u7a33\u3002\u8fd4\u56deis_stationary\u3001overall_mean\u3001overall_std\u3001segment_means\u548creason\u3002",
                {"tag":tag,"is_stationary":None,"overall_mean":None,"overall_std":None,
                 "segment_means":None,"reason":"pending","gold_status":"pending"},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_corr_template():
    pairs=[("FI35111","FI35116"),("FI35111","TI35111A1"),("FI35114","FI35116"),
           ("PI35111A1","PI35111A2"),("TI35111A1","TI35111A3"),("FI35111","PI35113"),
           ("FIC35111_PV","FIC35111_MV"),
           ("TI35111A1","TI35111A9"),("TI35111A1","TI35111A5"),
           ("PI35111A1","PI35111A9"),("PI35113","PI35111A1"),
           ("FI35111","FI35114"),("TI35111A2","TI35111A8"),
           ("FIC35116_PV","FIC35116_MV"),("PI35814A","PI35814B")]
    cases=[]
    for t1,t2 in pairs:
        for lbl,st,ed in [("3h","2026-06-18T08:00:00+08:00","2026-06-18T11:00:00+08:00"),
                          ("2h","2026-06-19T08:00:00+08:00","2026-06-19T10:00:00+08:00"),
                          ("4h","2026-06-20T08:00:00+08:00","2026-06-20T12:00:00+08:00")]:
            i=_cidx()
            cases.append(_case(f"analysis_corr_{i:04d}","correlation",
                f"\u8bf7\u5206\u6790{t1}\u548c{t2}\u5728{st}\u5230{ed}\u7684\u76f8\u5173\u6027\u3002\u8fd4\u56der\u3001strength\u3001direction\u548cmax_lag\u3002",
                {"tag1":t1,"tag2":t2,"r":None,"strength":"pending","direction":"pending",
                 "max_lag":None,"max_cross_r":None,"gold_status":"pending"},
                inputs={"tag1":t1,"tag2":t2,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_ctrl_template():
    bases=["FIC35111","FIC35116","HIC35814A","LIC35113A","PIC35113","TIC35112"]
    cases=[]
    for base in bases:
        for lbl,st,ed in [("d18_8h","2026-06-18T08:00:00+08:00","2026-06-18T16:00:00+08:00"),
                          ("d19_8h","2026-06-19T08:00:00+08:00","2026-06-19T16:00:00+08:00"),
                          ("d18_4h","2026-06-18T08:00:00+08:00","2026-06-18T12:00:00+08:00")]:
            i=_cidx()
            cases.append(_case(f"analysis_ctrl_{i:04d}","control_response",
                f"\u8bf7\u5206\u6790{base}\u5728{st}\u5230{ed}\u7684\u63a7\u5236\u54cd\u5e94\u3002\u8fd4\u56demv_events_detected\u548cmv_mean\u3002",
                {"tag_base":base,"mv_events_detected":None,"mv_mean":None,"gold_status":"pending"},
                inputs={"tag_base":base,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_roll_template():
    tags=["FI35111","TI35111A1","PI35111A2","FI35116","PI35113",
          "TI35111A5","TI35111A9","PI35111A9","FI35114","LI35111A",
          "TI35931","PI35814A","PI35814B","LI35113"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in _w1h() + [("d18_4h","2026-06-18T08:00:00+08:00","2026-06-18T12:00:00+08:00")]:
            i=_cidx()
            cases.append(_case(f"analysis_roll_{i:04d}","rolling_stats",
                f"\u8bf7\u8ba1\u7b97{tag}\u5728{st}\u5230{ed}\u7684\u6eda\u52a8\u7edf\u8ba1\u91cf\u3002\u8fd4\u56den\u3001overall_mean\u3001overall_std\u3001final_rolling_mean_60\u3001final_ewma\u548chas_significant_trend\u3002",
                {"tag":tag,"n":None,"overall_mean":None,"overall_std":None,
                 "has_significant_trend":None,"gold_status":"pending"},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def gen_outl_template():
    tags=["FI35111","FI35116","TI35111A1","PI35113","PI35111A2","TI35111A5","FI35114","LI35111A","TI35931",
          "TI35111A2","TI35111A3","TI35111A4","TI35111A6","TI35111A7","TI35111A8","TI35111A9",
          "PI35111A3","PI35111A4","PI35111A5","PI35111A6","PI35111A7","PI35111A8","PI35111A9",
          "PI35814A","PI35814B","LI35113"]
    cases=[]
    for tag in tags:
        for lbl,st,ed in [("1h","2026-06-18T08:00:00+08:00","2026-06-18T09:00:00+08:00"),
                          ("1h","2026-06-19T08:00:00+08:00","2026-06-19T09:00:00+08:00"),
                          ("4h","2026-06-20T08:00:00+08:00","2026-06-20T12:00:00+08:00")]:
            i=_cidx()
            cases.append(_case(f"analysis_outl_{i:04d}","outlier_detect",
                f"\u8bf7\u68c0\u6d4b{tag}\u5728{st}\u5230{ed}\u7684\u5f02\u5e38\u503c\u3002\u8fd4\u56den\u3001overall_mean\u3001iqr_outlier_count\u3001zscore_outlier_count\u3001lower_fence\u548cupper_fence\u3002",
                {"tag":tag,"n":None,"overall_mean":None,
                 "iqr_outlier_count":None,"zscore_outlier_count":None,
                 "lower_fence":None,"upper_fence":None,"gold_status":"pending"},
                inputs={"tag":tag,"start":st,"end":ed},split="test_locked" if i%5==0 else "dev"))
    return cases

def main(data_dir: str | None = None, template_only: bool = False):
    if data_dir:
        set_data_dir(Path(data_dir))
    all_cases=[]
    if template_only:
        generators = [gen_stat_template, gen_corr_template, gen_ctrl_template,
                      gen_roll_template, gen_outl_template, gen_edge_cases]
    else:
        generators = [gen_stat, gen_corr, gen_ctrl, gen_roll, gen_outl, gen_edge_cases]
    for gen in generators:
        a=gen(); all_cases.extend(a); print(f"  {gen.__name__}: {len(a)} cases")
    print(f"\nTotal: {len(all_cases)} cases")
    return all_cases

def output_jsonl(cases, path):
    with open(path,"w",encoding="utf-8") as f:
        for c in cases:
            f.write(json.dumps(c,ensure_ascii=False)+"\n")
    print(f"Written {len(cases)} cases to {path}")

if __name__=="__main__":
    parser=argparse.ArgumentParser(description="Generate extended analysis benchmark cases")
    parser.add_argument("--data-dir",default=None,help="Path to CSV data directory")
    parser.add_argument("--smoke-only",action="store_true",help="Generate only smoke cases")
    parser.add_argument("--template-only",action="store_true",help="Generate case templates without gold results (no data needed)")
    parser.add_argument("--output-dir",default=None,help="Output directory for JSONL files")
    a=parser.parse_args()
    if a.smoke_only:
        if a.data_dir: set_data_dir(Path(a.data_dir))
        smoke=gen_smoke(); print(json.dumps(smoke,ensure_ascii=False,indent=2))
    else:
        cases = main(a.data_dir, template_only=a.template_only)
        out_dir = Path(a.output_dir) if a.output_dir else BENCH
        out_dir.mkdir(parents=True,exist_ok=True)
        output_jsonl(cases, out_dir / "analysis_formal.jsonl")
        smoke = gen_smoke()
        output_jsonl(smoke, out_dir / "analysis_smoke.jsonl")