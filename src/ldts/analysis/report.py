from __future__ import annotations
import csv, html, json
from collections import Counter, defaultdict
from pathlib import Path

def read_rows(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def _write(path: Path, rows: list[dict]):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)

def _percentile(values, p):
    if not values: return ""
    values = sorted(values); index = (len(values) - 1) * p; lo, hi = int(index), min(int(index) + 1, len(values) - 1)
    return round(values[lo] + (values[hi] - values[lo]) * (index - lo), 2)

def summarize(rows: list[dict]):
    def count(field): return Counter(r.get(field, "") for r in rows if r.get(field, ""))
    prices = [float(r["representative_price_twd"]) for r in rows if r.get("representative_price_twd")]
    city_counts = count("縣市")
    institution_city = defaultdict(set)
    for r in rows:
        if r.get("縣市") and r.get("medical_institution_name_normalized"): institution_city[r["縣市"]].add(r["medical_institution_name_normalized"])
    return {"rows": len(rows), "unique_case_ids": len({r.get("案件編號") for r in rows}), "institutions": len(count("medical_institution_name_normalized")), "laboratories": len(count("accredited_lab_name_normalized")), "categories": dict(count("檢測項目類別")), "median_price_twd": sorted(prices)[len(prices)//2] if prices else None, "institution_counts": dict(count("medical_institution_name_normalized")), "laboratory_counts": dict(count("accredited_lab_name_normalized")), "panel_size_counts": dict(count("panel_size_group")), "city_counts": dict(city_counts), "city_institutions": {k: len(v) for k,v in institution_city.items()}, "city_institution_names": {k: sorted(v) for k,v in institution_city.items()}}

def build_report(input_csv: Path | list[Path], output_dir: Path, categories: list[str] | None = None) -> Path:
    paths = input_csv if isinstance(input_csv, list) else [input_csv]
    rows = [row for path in paths for row in read_rows(path)]
    for row in rows:
        row["縣市"] = (row.get("縣市", "") or "").replace("台", "臺")
    if categories:
        rows = [row for row in rows if row.get("檢測項目類別", "") in categories]
    summary = summarize(rows); output_dir.mkdir(parents=True, exist_ok=True)
    all_cities = ["臺北市","新北市","桃園市","臺中市","臺南市","高雄市","基隆市","新竹市","嘉義市","新竹縣","苗栗縣","彰化縣","南投縣","雲林縣","嘉義縣","屏東縣","宜蘭縣","花蓮縣","臺東縣","澎湖縣","金門縣","連江縣"]
    city_summary = [{"city": city, "case_count": summary["city_counts"].get(city, 0), "institution_count": summary["city_institutions"].get(city, 0)} for city in all_cities]
    groups = defaultdict(list)
    for r in rows:
        try: groups[r.get("panel_size_group", "unknown")].append(float(r.get("representative_price_twd", "")))
        except (ValueError, TypeError): pass
    panel_prices = []
    for group, values in sorted(groups.items()):
        panel_prices.append({"panel_size_group": group, "count": len(values), "min_twd": min(values) if values else "", "p25_twd": _percentile(values, .25), "median_twd": _percentile(values, .5), "p75_twd": _percentile(values, .75), "max_twd": max(values) if values else ""})
    edges = Counter((r.get("medical_institution_name_normalized", ""), r.get("accredited_lab_name_normalized", "")) for r in rows if r.get("medical_institution_name_normalized") and r.get("accredited_lab_name_normalized"))
    institutions = sorted({a for a,b in edges}); laboratories = sorted({b for a,b in edges})
    network = {"edges": [{"institution": a, "laboratory": b, "count": n} for (a,b), n in edges.items()], "institutions": institutions, "laboratories": laboratories,
               "rows": [{"city": r.get("縣市", ""), "institution": r.get("medical_institution_name_normalized", ""), "laboratory": r.get("accredited_lab_name_normalized", ""), "test": r.get("檢測項目名稱", ""), "category": r.get("檢測項目類別", ""), "panel": r.get("panel_size_group", ""), "price": r.get("費用(新台幣)", r.get("費用（新台幣）", ""))} for r in rows]}
    _write(output_dir / "institutions.csv", [{"institution": k, "case_count": v} for k,v in summary["institution_counts"].items()])
    _write(output_dir / "laboratories.csv", [{"laboratory": k, "case_count": v} for k,v in summary["laboratory_counts"].items()])
    _write(output_dir / "categories.csv", [{"category": k, "case_count": v} for k,v in summary["categories"].items()])
    _write(output_dir / "panel_sizes.csv", [{"panel_size_group": k, "case_count": v} for k,v in summary["panel_size_counts"].items()])
    _write(output_dir / "panel_price_summary.csv", panel_prices)
    _write(output_dir / "city_summary.csv", city_summary)
    def table(title, mapping):
        body = "".join(f"<tr><td>{html.escape(str(k))}</td><td>{v}</td></tr>" for k,v in mapping.items())
        return f"<h2>{title}</h2><table><tr><th>項目</th><th>案件數</th></tr>{body}</table>"
    city_coords = {"臺北市":[25.0375,121.5637],"新北市":[25.0169,121.4628],"桃園市":[24.9937,121.3010],"臺中市":[24.1477,120.6736],"臺南市":[22.9997,120.2270],"高雄市":[22.6273,120.3014],"基隆市":[25.1276,121.7392],"新竹市":[24.8138,120.9675],"嘉義市":[23.4801,120.4491],"新竹縣":[24.8387,121.0177],"苗栗縣":[24.5602,120.8214],"彰化縣":[24.0518,120.5161],"南投縣":[23.9609,120.9719],"雲林縣":[23.7092,120.4313],"嘉義縣":[23.4589,120.5740],"屏東縣":[22.5519,120.5487],"宜蘭縣":[24.7021,121.7378],"花蓮縣":[23.9911,121.6112],"臺東縣":[22.7554,121.1500],"澎湖縣":[23.5711,119.5793],"金門縣":[24.4493,118.3767],"連江縣":[26.1605,119.9510]}
    chart_data = json.dumps({"institutions": summary["institution_counts"], "laboratories": summary["laboratory_counts"], "categories": summary["categories"], "panel_sizes": summary["panel_size_counts"], "city_counts": summary["city_counts"], "city_institutions": summary["city_institutions"], "city_institution_names": summary["city_institution_names"], "city_coords": city_coords, "network": network}, ensure_ascii=False)
    price_table = "<h2>Panel size 價格摘要</h2><table><tr><th>Panel 分組</th><th>案件數</th><th>最低價</th><th>P25</th><th>中位數</th><th>P75</th><th>最高價</th></tr>" + "".join(f"<tr><td>{html.escape(str(x['panel_size_group']))}</td><td>{x['count']}</td><td>{x['min_twd']}</td><td>{x['p25_twd']}</td><td>{x['median_twd']}</td><td>{x['p75_twd']}</td><td>{x['max_twd']}</td></tr>" for x in panel_prices) + "</table>"
    report = f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><title>LDTS 分析原型</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script><link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>body{{font-family:system-ui,sans-serif;max-width:1100px;margin:2rem auto;line-height:1.6}}table{{border-collapse:collapse;margin:.5rem 0 1rem;width:48%;display:inline-table;vertical-align:top;font-size:.9rem}}th,td{{border:1px solid #ccc;padding:.3rem .5rem;text-align:left}}th{{background:#e8f4f8}}.note{{background:#fff8df;padding:1rem}}.chart{{min-height:300px;display:inline-block;width:32%;vertical-align:top}}#top10_institutions,#top10_laboratories{{width:48%;min-height:430px}}#network{{display:block;width:100%;min-height:420px;position:relative}}#network .hovertext{{display:none!important}}#map{{height:420px;max-width:900px}}@media(max-width:800px){{.chart,table{{width:100%}}}}</style>
<h1>LDTS 分析原型報告</h1><p class="note">本報告目前只使用指定 CSV；登記案件數不等於實際檢測量或市場營收，機構所在地也不等於實際服務範圍。</p>
<h2>摘要</h2><ul><li>案件數：{summary['rows']}</li><li>案件編號：{summary['unique_case_ids']}</li><li>醫療機構數：{summary['institutions']}</li><li>認證實驗室數：{summary['laboratories']}</li><li>價格中位數（TWD）：{summary['median_price_twd'] or '無法計算'}</li></ul>
<h2>互動圖表</h2><label for="city_filter">縣市：</label><select id="city_filter"><option value="ALL">全部縣市</option></select><div id="institutions" class="chart"></div><div id="laboratories" class="chart"></div><div id="categories" class="chart"></div><div id="panel_sizes" class="chart"></div>
<h2>合作網絡與 Portfolio Explorer</h2><p>下圖顯示登記資料中的醫療機構—認證實驗室關係。選擇任一方可查看合作對象與檢測項目；這不是檢體量或營收網絡。</p><div id="network" class="chart"></div><label for="entity_search">選擇或搜尋醫療機構／認證實驗室：</label><select id="entity" style="display:none"></select><input id="entity_search" type="search" list="entity_options" placeholder="輸入名稱搜尋或選擇建議" autocomplete="off"><datalist id="entity_options"></datalist><div id="details"></div><section id="portfolio_pies"><div id="top10_institutions" class="chart"></div><div id="top10_laboratories" class="chart"></div></section>
<h2>登記縣市簡圖</h2><p>地圖使用縣市代表點；機構點為同縣市內的示意分散位置，不是實際地址或經緯度。</p><div id="map"></div>
{table('檢測類別', summary['categories'])}{table('Panel size', summary['panel_size_counts'])}
{price_table}
<h2>方法與限制</h2><p>價格中位數使用已成功解析的 representative_price_twd。每基因價格只適用於明確基因 panel；大型 panel、WES/WGS 與未知基因數不應直接比較。</p></html>'''
    report = report.replace('</html>', f'''<script>
const data={chart_data};
const citySelect=document.getElementById('city_filter'); [...new Set(data.network.rows.map(r=>r.city).filter(Boolean))].sort().forEach(c=>{{const o=document.createElement('option');o.value=c;o.textContent=c;citySelect.appendChild(o);}});
function filteredRows(){{const c=citySelect.value;return data.network.rows.filter(r=>c==='ALL'||r.city===c);}}
function counts(rows,key){{const out={{}};rows.forEach(r=>{{if(r[key])out[r[key]]=(out[r[key]]||0)+1;}});return out;}}
const topSelect=document.createElement('select'); topSelect.id='top_n'; ['10','20','ALL'].forEach(v=>{{const o=document.createElement('option');o.value=v;o.textContent=v==='ALL'?'全部':'Top '+v;topSelect.appendChild(o);}}); document.getElementById('institutions').parentNode.insertBefore(topSelect,document.getElementById('institutions'));
function limited(obj){{const n=topSelect.value==='ALL'?999999:Number(topSelect.value);return Object.fromEntries(Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,n));}}
function bar(id,title,obj) {{ const limitedObj=(id==='categories'||id==='panel_sizes')?obj:limited(obj), labels=Object.keys(limitedObj), values=Object.values(limitedObj); Plotly.react(id,[{{x:values,y:labels,type:'bar',orientation:'h',text:values,textposition:'auto',marker:{{color:'#168aad'}}}}],{{title,margin:{{l:220,r:30,t:60,b:45}},xaxis:{{title:'案件數'}},yaxis:{{automargin:true}}}},{{responsive:true,displaylogo:false}}); }}
function drawCharts(){{const rows=filteredRows();bar('institutions','醫療機構案件數',counts(rows,'institution'));bar('laboratories','認證實驗室案件數',counts(rows,'laboratory'));bar('categories','檢測類別案件數',counts(rows,'category'));bar('panel_sizes','Panel size 案件數',counts(rows,'panel'));}}
function drawNetwork(){{const base=filteredRows(), n=topSelect.value==='ALL'?999999:Number(topSelect.value), ic=counts(base,'institution'), topInstitutions=new Set(Object.keys(ic).sort((a,b)=>ic[b]-ic[a]).slice(0,n)), rows=topSelect.value==='ALL'?base:base.filter(r=>topInstitutions.has(r.institution)), edges={{}};rows.forEach(r=>{{if(r.institution&&r.laboratory){{const k=r.institution+'|||'+r.laboratory;edges[k]=(edges[k]||0)+1;}}}});const pairs=Object.entries(edges).map(([k,count])=>{{const [institution,laboratory]=k.split('|||');return {{institution,laboratory,count}};}});const ins=[...new Set(pairs.map(e=>e.institution))],labs=[...new Set(pairs.map(e=>e.laboratory))],nodes=[...ins,...labs],idx=new Map(nodes.map((x,i)=>[x,i]));window._networkPairs=pairs;window._networkNodes=nodes;Plotly.react('network',[{{type:'sankey',orientation:'h',node:{{label:nodes,color:nodes.map((x,i)=>i<ins.length?'#168aad':'#f08c46')}},link:{{source:pairs.map(e=>idx.get(e.institution)),target:pairs.map(e=>idx.get(e.laboratory)),value:pairs.map(e=>e.count),label:pairs.map(e=>e.count+' 案'),color:pairs.map(()=> '#b8c4ce')}}}}],{{title:'Top 醫療機構的全部合作網絡',font:{{size:12}},margin:{{t:70,r:260,l:220,b:40}},hoverlabel:{{align:'left',namelength:-1}}}},{{responsive:true,displaylogo:false}});}}
const select=document.getElementById('entity'), entitySearch=document.getElementById('entity_search'), entityOptions=document.getElementById('entity_options');
function chooseEntity(text){{const option=[...select.options].find(o=>o.textContent===text);if(option){{select.value=option.value;entitySearch.value=option.textContent;showDetails();}}}}
entitySearch.addEventListener('input',()=>{{const exact=[...select.options].some(o=>o.textContent===entitySearch.value);if(exact)chooseEntity(entitySearch.value);}});entitySearch.addEventListener('change',()=>chooseEntity(entitySearch.value));entitySearch.addEventListener('focus',()=>entitySearch.select());
function updateEntities(){{select.innerHTML='';entityOptions.innerHTML='';entitySearch.value='';const rows=filteredRows();const ins=[...new Set(rows.map(r=>r.institution).filter(Boolean))].sort();const labs=[...new Set(rows.map(r=>r.laboratory).filter(Boolean))].sort();[...ins.map(x=>['醫療機構',x]),...labs.map(x=>['認證實驗室',x])].forEach(([kind,name])=>{{const text=kind+'：'+name,o=document.createElement('option'),d=document.createElement('option');o.value=kind+'|'+name;o.textContent=text;d.value=text;select.appendChild(o);entityOptions.appendChild(d);}});if(select.options.length){{select.selectedIndex=0;entitySearch.value=select.options[0].textContent;showDetails();}}else{{document.getElementById('details').textContent='此縣市目前沒有可顯示的登記關係。';}}}}
function drawPortfolioPies(){{const top=obj=>Object.entries(obj).sort((a,b)=>b[1]-a[1]).slice(0,10);function pie(id,title,obj){{const x=top(obj);Plotly.react(id,[{{type:'pie',labels:x.map(a=>a[0]),values:x.map(a=>a[1]),textinfo:'percent',hovertemplate:'%{{label}}<br>案件數：%{{value}}<extra></extra>'}}],{{title,margin:{{t:60,b:35,l:80,r:80}},height:400}},{{responsive:true,displaylogo:false}});}}pie('top10_institutions','Top 10 醫療機構（全臺）',counts(data.network.rows,'institution'));pie('top10_laboratories','Top 10 認證實驗室（全臺）',counts(data.network.rows,'laboratory'));}}
function showDetails(){{if(!select.value)return;const [kind,name]=select.value.split('|'); const matching=filteredRows().filter(r=>kind==='醫療機構'?r.institution===name:r.laboratory===name); const partners=[...new Set(matching.map(r=>kind==='醫療機構'?r.laboratory:r.institution))]; const tests=[...new Set(matching.map(r=>r.test).filter(Boolean))]; document.getElementById('details').innerHTML='<p><b>'+name+'</b>｜案件 '+matching.length+'｜合作'+(kind==='醫療機構'?'實驗室':'醫療機構')+' '+partners.length+' 家</p><p>合作對象：'+partners.join('、')+'</p><p>檢測項目：'+tests.join('、')+'</p>';}} select.addEventListener('change',()=>{{entitySearch.value=select.options[select.selectedIndex].textContent;showDetails();drawNetwork();}});topSelect.addEventListener('change',()=>{{drawCharts();drawNetwork();}});
citySelect.addEventListener('change',()=>{{drawCharts();updateEntities();drawNetwork();}});drawCharts();updateEntities();drawNetwork();drawPortfolioPies();setTimeout(()=>{{const networkElement=document.getElementById('network');if(!networkElement||typeof networkElement.on!=='function')return;let tip=document.getElementById('network_hover_tip');if(!tip){{tip=document.createElement('div');tip.id='network_hover_tip';tip.style.cssText='position:absolute;right:12px;top:12px;background:#fff;border:1px solid #888;padding:8px;z-index:10;display:none;max-width:320px;font-size:13px;';networkElement.style.position='relative';networkElement.appendChild(tip);}}networkElement.on('plotly_hover',ev=>{{const p=ev.points&&ev.points[0];if(!p)return;const label=p.label||'';const pairs=window._networkPairs||[];const nodes=window._networkNodes||[];const related=pairs.map((e,i)=>({{e,i}})).filter(x=>x.e.institution===label||x.e.laboratory===label).map(x=>x.i);const links=pairs.map((e,i)=>related.includes(i)?'#d94841':'rgba(180,190,200,.18)');const colors=nodes.map(n=>n===label?'#d94841':'#c9cdd1');if(pairs.length)Plotly.restyle(networkElement,{{'link.color':[links],'node.color':[colors]}},[0]);tip.innerHTML='<b>'+label+'</b><br>相關案件數：'+related.reduce((a,i)=>a+pairs[i].count,0)+'<br>合作連線數：'+related.length;tip.style.display='block';}});networkElement.on('plotly_unhover',()=>{{tip.style.display='none';const pairs=window._networkPairs||[],nodes=window._networkNodes||[];if(pairs.length)Plotly.restyle(networkElement,{{'link.color':[pairs.map(()=> '#b8c4ce')],'node.color':[nodes.map((n,i)=>i<nodes.length/2?'#168aad':'#f08c46')]}},[0]);}});networkElement.on('plotly_click',ev=>{{const p=ev.points&&ev.points[0];if(!p)return;const labels=(p.data&&p.data.node&&p.data.node.label)||[];const label=labels[p.pointNumber]||p.label||'';const opt=[...select.options].find(o=>o.textContent.includes(label));if(opt){{select.value=opt.value;entitySearch.value=opt.textContent;showDetails();}}}});}},300);
const networkNode=document.getElementById('network'), entityNode=document.getElementById('entity'), entityLabel=document.querySelector('label[for="entity_search"]'), detailsNode=document.getElementById('details'), pieNode=document.getElementById('portfolio_pies'), chartNode=document.getElementById('institutions'); const networkHeading=[...document.querySelectorAll('h2')].find(x=>x.textContent.includes('Portfolio Explorer')); const networkIntro=networkHeading?.nextElementSibling; if(networkHeading)chartNode.parentNode.insertBefore(networkHeading,chartNode); if(networkIntro)chartNode.parentNode.insertBefore(networkIntro,chartNode); chartNode.parentNode.insertBefore(entityLabel,chartNode); chartNode.parentNode.insertBefore(entitySearch,chartNode); chartNode.parentNode.insertBefore(entityNode,chartNode); chartNode.parentNode.insertBefore(networkNode,chartNode); chartNode.parentNode.insertBefore(detailsNode,chartNode); chartNode.parentNode.insertBefore(pieNode,chartNode);
const map=L.map('map').setView([23.75,120.95],7); L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{attribution:'© OpenStreetMap contributors'}}).addTo(map);
Object.entries(data.city_coords).forEach(([city, pos])=>{{ if(!data.city_counts[city]) return; const n=data.city_counts[city], m=data.city_institutions[city]||0; L.circleMarker(pos,{{radius:Math.max(7,Math.min(22,5+n*1.4)),color:'#168aad',fillOpacity:.65}}).addTo(map).bindPopup(city+'<br>案件數：'+n+'<br>醫療機構數：'+m); }});
Object.entries(data.city_institution_names).forEach(([city, names])=>{{ const base=data.city_coords[city]; if(!base) return; names.forEach((name,i)=>{{ const a=(i*2.399)%6.28, d=.018+((i*7)%5)*.006; L.circleMarker([base[0]+Math.sin(a)*d,base[1]+Math.cos(a)*d],{{radius:4,color:'#f08c46',fillOpacity:.7}}).addTo(map).bindPopup(city+'<br>示意機構：'+name+'<br><small>非實際地址</small>'); }}); }});
</script></html>''')
    path = output_dir / "ldts_analysis_report.html"; path.write_text(report, encoding="utf-8")
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return path
