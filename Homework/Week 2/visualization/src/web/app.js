/* Drawing and interaction only; all research results come from the Python API. */
"use strict";
const $ = id => document.getElementById(id);
const state = {mode:"buyers", focus:"335", year:2025, baseline:2019, sort:"amount", selected:null};
let catalog, view, requestNumber = 0, metric = "amount";
const NS = "http://www.w3.org/2000/svg";

function text(id, value) { $(id).textContent = value; }
function option(value, label) {
  const node = document.createElement("option");
  node.value = value; node.textContent = label; return node;
}
function choices() {
  $("focus").replaceChildren();
  const axis = state.mode === "inputs" ? catalog.industries : catalog.products;
  if(!axis.some(item=>item.id===state.focus)) state.focus=axis[0].id;
  axis.forEach(item => $("focus").append(option(item.id, item.name)));
  $("focus").value = state.focus;
  text("focus-label", state.mode === "inputs" ? "Buying industry" : "Product category");
  ["inputs","buyers"].forEach(id => $(id).setAttribute("aria-pressed", String(state.mode === id)));
}
function params(includeSelected=true) {
  const p = new URLSearchParams({mode:state.mode, focus:state.focus, year:state.year, baseline:state.baseline, sort:state.sort});
  if(includeSelected && state.selected) p.set("selected",state.selected);
  return p;
}
async function refresh() {
  const sequence = ++requestNumber;
  $("results").hidden = true; $("status").hidden = false;
  $("status").className = "status"; text("status","Reading annual purchase flows…");
  try {
    const response = await fetch("/api/flows?" + params());
    if(!response.ok) throw new Error("The data request failed. Check the selected years and try again.");
    const data = await response.json();
    if(sequence !== requestNumber) return;
    view = data; state.selected = data.selected;
    render();
    $("status").hidden = true; $("results").hidden = false;
  } catch(error) {
    if(sequence !== requestNumber) return;
    text("status",error.message); $("status").className = "status error";
  }
}
function render() {
  const inputs = view.mode === "inputs";
  text("context", inputs ? "INDUSTRY INPUTS" : "INDUSTRIAL BUYERS");
  text("focus-name",view.focus_name);
  text("denominator",view.denominator_label);
  text("total",view.total_label);
  text("total-change",view.total_change_label + " nominal change since " + view.baseline);
  text("ranking-title",state.sort === "share_change" ? "Relationships gaining share" : (inputs ? "Largest input purchases" : "Largest industrial buyers"));
  text("row-label", inputs ? "Product category" : "Buying industry");
  text("insight",view.insight);
  text("rows-note",view.rows.length + " numeric relationships · " + view.missing_count + " unreported. Scroll for all.");
  $("export").href = "/api/export?" + params(false);
  $("rows").replaceChildren();
  const max = Math.max(1,...view.rows.map(row=>Math.abs(row.amount)));
  for(const row of view.rows) {
    const tr = document.createElement("tr");
    if(row.id === view.selected) tr.className = "selected";
    const label = document.createElement("td"), button = document.createElement("button");
    button.textContent = row.name;
    button.setAttribute("aria-pressed",String(row.id === view.selected));
    button.addEventListener("click",()=>{state.selected=row.id;refresh();});
    label.append(button);
    const track = document.createElement("div"), bar = document.createElement("span");
    track.className="bar-track"; bar.className="bar";
    bar.style.width = Math.abs(row.amount)/max*100 + "%";
    if(row.amount<0) bar.style.background="#b77540";
    track.append(bar); label.append(track); tr.append(label);
    [row.amount_label,row.share_label,row.share_change_label].forEach((value,i)=>{
      const td=document.createElement("td");td.textContent=value;
      if(i===2 && row.share_change!==null) td.className=row.share_change<0?"negative":"positive";
      tr.append(td);
    });
    $("rows").append(tr);
  }
  text("from",inputs ? view.selected_name || "No reported product" : view.focus_name);
  text("to",inputs ? view.focus_name : view.selected_name || "No reported buyer");
  $("annual").replaceChildren();
  view.series.forEach(point=>{
    const tr=document.createElement("tr");
    [point.year,point.amount_label,point.share_label].forEach(value=>{
      const td=document.createElement("td");td.textContent=value;tr.append(td);
    });
    $("annual").append(tr);
  });
  text("provenance","BEA · Use Summary · Snapshot " + view.source.retrieved_at.slice(0,10) + " · Current U.S. dollars");
  drawTrend();
}
function svg(tag, attributes={}, label) {
  const node=document.createElementNS(NS,tag);
  Object.entries(attributes).forEach(([key,value])=>node.setAttribute(key,value));
  if(label!==undefined) node.textContent=label;
  return node;
}
function drawTrend() {
  const chart=$("trend");chart.replaceChildren();
  document.querySelectorAll("[data-metric]").forEach(b=>b.setAttribute("aria-pressed",String(b.dataset.metric===metric)));
  const current = view.series.find(p=>p.year===view.year);
  const relation = view.rows.find(r=>r.id===view.selected);
  text("relationship-value",current ? current[metric+"_label"] : "Not reported");
  text("relationship-change",relation ? (metric==="amount"?relation.change_label:relation.share_change_label)+" vs "+view.baseline : "");
  text("chart-note",metric==="amount" ? "Annual nominal purchases. Prices and volumes both affect this line. Select a point to inspect its year." : view.denominator_label+". Changes are percentage points, not percentage growth.");
  const values=view.series.map(p=>p[metric]);
  const valid=values.filter(v=>v!==null);
  if(!valid.length){chart.append(svg("text",{x:20,y:110},"No reported values for this relationship."));return;}
  const min=Math.min(0,...valid),max=Math.max(0,...valid),range=max-min||1;
  const left=26,right=458,top=26,bottom=215;
  const x=i=>left+i*(right-left)/Math.max(1,view.series.length-1);
  const y=v=>bottom-(v-min)/range*(bottom-top);
  [0,.5,1].forEach(t=>chart.append(svg("line",{x1:left,x2:right,y1:top+t*(bottom-top),y2:top+t*(bottom-top),stroke:"#e5e9e3","stroke-dasharray":"3 4"})));
  chart.append(svg("line",{x1:left,x2:right,y1:y(0),y2:y(0),stroke:"#d5ddd4"}));
  let path="",pen=false;
  view.series.forEach((point,i)=>{
    if(point[metric]===null){pen=false;return;}
    path+=(pen?" L":" M")+x(i)+" "+y(point[metric]);pen=true;
  });
  chart.append(svg("path",{d:path,fill:"none",stroke:"#1b6654","stroke-width":2.4,"stroke-linejoin":"round"}));
  view.series.forEach((point,i)=>{
    if(i===0 || i===view.series.length-1 || point.year%5===0){
      chart.append(svg("text",{x:x(i),y:241,"text-anchor":"middle"},point.year));
    }
    if(point[metric]===null)return;
    const active=point.year===view.year, baseline=point.year===view.baseline;
    if(active||baseline){
      chart.append(svg("line",{x1:x(i),x2:x(i),y1:top,y2:bottom,stroke:active?"#91ad9b":"#d6ac80","stroke-dasharray":"3 4"}));
      const anchor=i>view.series.length-5?"end":i<4?"start":"middle";
      chart.append(svg("text",{x:x(i),y:Math.max(14,y(point[metric])-12),"text-anchor":anchor},point[metric+"_label"]));
    }
    const dot=svg("circle",{cx:x(i),cy:y(point[metric]),r:active?5:baseline?4:3,fill:baseline&&!active?"#b77540":"#1b6654"});
    dot.append(svg("title",{},point.year+": "+point[metric+"_label"]));chart.append(dot);
    const hit=svg("circle",{cx:x(i),cy:y(point[metric]),r:8,fill:"transparent",tabindex:0,role:"button","aria-label":point.year+": "+point[metric+"_label"]});
    const select=()=>{state.year=point.year;$("year").value=point.year;refresh();};
    hit.addEventListener("click",select);hit.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();select();}});
    chart.append(hit);
  });
  chart.append(svg("title",{},view.selected_name+"; "+(metric==="amount"?"annual purchase dollars":"annual share of intermediate total")+". Exact values in the annual values table."));
}
async function init() {
  if(location.protocol==="file:"){
    $("file-notice").hidden=false;text("status","Open the local app above to load data.");return;
  }
  try {
    const response=await fetch("/api/catalog");
    if(!response.ok)throw new Error("The BEA source data could not be loaded.");
    catalog=await response.json();
    catalog.years.forEach(year=>{$("year").append(option(year,year));$("baseline").append(option(year,year));});
    state.year=catalog.years[catalog.years.length-1];
    $("year").value=state.year;$("baseline").value=state.baseline;
    text("coverage",catalog.years[0]+"–"+state.year);
    choices();
    ["inputs","buyers"].forEach(mode=>$(mode).addEventListener("click",()=>{
      state.mode=mode;state.selected=null;choices();refresh();
    }));
    ["focus","year","baseline","sort"].forEach(id=>$(id).addEventListener("change",()=>{
      state[id]=(id==="year"||id==="baseline")?Number($(id).value):$(id).value;
      if(id==="focus")state.selected=null;
      refresh();
    }));
    document.querySelectorAll("[data-focus]").forEach(button=>button.addEventListener("click",()=>{
      state.mode=button.dataset.mode;state.focus=button.dataset.focus;state.selected=null;
      state.sort="amount";$("sort").value="amount";choices();refresh();
    }));
    document.querySelectorAll("[data-metric]").forEach(button=>button.addEventListener("click",()=>{metric=button.dataset.metric;if(view)drawTrend();}));
    await refresh();
  }catch(error){text("status",error.message);$("status").className="status error";}
}
init();
