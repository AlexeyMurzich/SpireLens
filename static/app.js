'use strict';
const $ = s => document.querySelector(s);
const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = x => new Intl.NumberFormat('ru-RU',{maximumFractionDigits:1}).format(x ?? 0);
const resultNames = {win:'Победа',loss:'Поражение',abandoned:'Прерван'};
const types = {ancient:'Древний',monster:'Бой',elite:'Элита',boss:'Босс',rest_site:'Костёр',shop:'Магазин',treasure:'Сокровище',unknown:'Событие',event:'Событие'};
const ids=['profile','character','ascension','mode','party','outcome','from','to','min_floor','version','exclude_abandoned'];
let meta, data, tab='overview', page=0, search='', generation=0, busy=false;
function query(){const q=new URLSearchParams();for(const id of ids){const el=$('#'+id);const v=el.type==='checkbox'?(el.checked?'1':''):el.value;if(v)q.set(id,v);}return q.toString();}
async function api(path){const r=await fetch(path);const d=await r.json();if(!r.ok)throw Error(d.error||'Не удалось прочитать данные');return d;}
function error(e){$('#error').textContent=e.message;$('#error').classList.remove('hidden');}
function panel(title,body,caption=''){return `<section class="panel"><div class="panel-head"><h2>${title}</h2><span class="caption">${caption}</span></div>${body}</section>`;}
function table(head,rows){return `<div class="table-wrap"><table><thead><tr>${head.map(x=>`<th>${x}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table></div>`;}
function metric(label,value,sub){return `<div class="metric"><div class="label">${label}</div><strong>${value}</strong><small>${sub}</small></div>`;}
function badge(r){return `<span class="tag ${r.outcome}" title="${r.inferred?'Поражение предположительно определено по нулевому HP; исходный флаг игры — прерван':'Результат по истории игры'}">${resultNames[r.outcome]}${r.inferred?' *':''}</span>`;}
function runRows(runs){return runs.map(r=>`<tr data-run="${r.id}" tabindex="0" role="button" aria-label="Открыть забег ${esc(r.date)}"><td>${esc(r.date)}</td><td>${esc(r.character_name)}${r.coop?' · кооп':''}</td><td>A${r.ascension}</td><td>${badge(r)}</td><td>${r.floors}</td><td>${Math.round(r.duration/60)} мин</td><td>${r.deck_size}</td><td class="muted">${esc(r.cause_name)}</td></tr>`);}
function trendChart(items){
 if(!items.length)return '<div class="empty">Пока нет забегов</div>';
 const W=720,H=150,pad=14,max=Math.max(10,...items.map(r=>r.floors));
 const points=items.map((r,i)=>[pad+i*(W-pad*2)/Math.max(1,items.length-1),H-pad-r.floors*(H-pad*2)/max]);
 return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Достигнутые этажи последних ${items.length} забегов">${[0,1,2].map(i=>`<line x1="0" x2="${W}" y1="${pad+i*(H-2*pad)/2}" y2="${pad+i*(H-2*pad)/2}" stroke="#303a3d" stroke-dasharray="3 5"/>`).join('')}<polyline points="${points.map(p=>p.join(',')).join(' ')}" fill="none" stroke="#718c73" stroke-width="1.7"/>${points.map(([x,y],i)=>`<circle cx="${x}" cy="${y}" r="${items[i].win?4:2.7}" fill="${items[i].win?'#b4d990':'#7d8990'}"><title>${esc(items[i].character)} · этаж ${items[i].floors} · ${items[i].win?'победа':'без победы'}</title></circle>`).join('')}</svg><div class="legend"><span>● Победа — светлая точка</span><span>Слева старые → справа новые · высота = этаж</span></div>`;
}
function overview(){
 const s=data.summary;
 const stats=`<div class="stats">${metric('ПРОЦЕНТ ПОБЕД',`${num(s.rate)}<span style="font-size:18px">%</span>`,`${num(s.wins)} побед / ${num(s.count)} забегов`)}${metric('ПРОЙДЕНО В СРЕДНЕМ',num(s.avg_floor),'этажей за забег')}${metric('ВРЕМЯ В ЗАБЕГАХ',`${num(s.hours)}<span style="font-size:18px"> ч</span>`,'по таймеру истории игры')}${metric('ПОРАЖЕНИЯ / ПРЕРВАНЫ',`${num(s.losses)} / ${num(s.abandoned)}`,'* поражения по косвенным признакам')}</div>`;
 const bars=data.characters.map(c=>`<div class="bar-row"><span>${esc(c.name)}<br><small class="muted">${c.count} забегов</small></span><div class="bar"><i style="width:${c.rate}%"></i></div><span class="positive">${num(c.rate)}%</span></div>`).join('');
 const asc=data.ascensions.sort((a,b)=>+a.key-+b.key).map(c=>`<tr><td>A${esc(c.key)}</td><td>${c.count}</td><td>${c.wins}</td><td class="positive">${num(c.rate)}%</td><td>${num(c.floors)}</td></tr>`);
 return stats+`<div class="grid">${panel('Траектория восхождений',trendChart(data.trend),'Последние 80 в выборке')}${panel('По персонажам',bars||'<p>Нет данных</p>','Доля побед')}</div><div class="grid">${panel('Что заметно в ваших забегах',data.insights.map(i=>`<div class="insight">${esc(i)}</div>`).join('')||'<p>Для выводов нужно больше данных.</p>')}${panel('Сложность и результат',table(['Уровень','Забеги','Победы','% побед','Ср. этаж'],asc))}</div>`+panel('Последние забеги',table(['Дата','Персонаж','Уровень','Итог','Этаж','Время','Колода','Встреча при завершении'],runRows(data.runs.slice(0,8))),'Нажмите строку для разбора');
}
function history(){
 const runs=data.runs.filter(r=>[r.character_name,r.cause_name,r.seed,r.date].some(x=>String(x).toLowerCase().includes(search.toLowerCase())));
 const pages=Math.max(1,Math.ceil(runs.length/50));page=Math.min(page,pages-1);
 return panel('История забегов',`<div class="toolbar"><input id="search" type="search" placeholder="Персонаж, враг, seed, дата…" value="${esc(search)}" aria-label="Поиск по истории"><a class="secondary" href="/api/export.csv?${esc(query())}">Скачать CSV по фильтрам</a></div>${table(['Дата','Персонаж','Уровень','Итог','Этаж','Время','Колода','Встреча при завершении'],runRows(runs.slice(page*50,page*50+50)))}<div class="pager"><span>${runs.length} забегов · ${page+1} / ${pages}</span><button class="secondary" id="prev" ${page===0?'disabled':''}>←</button><button class="secondary" id="next" ${page+1>=pages?'disabled':''}>→</button></div>`,'По 50 на странице');
}
function cards(){
 const matches=x=>x.name.toLowerCase().includes(search.toLowerCase());
 const cr=data.cards.filter(matches).map(c=>`<tr><td title="${esc(c.id)}">${esc(c.name)}</td><td>${c.offered}</td><td>${c.picked}</td><td>${num(c.pick_rate)}%</td><td>${c.wins}</td><td class="${c.picked<10?'muted':'positive'}">${c.rate===null?'—':num(c.rate)+'%'}${c.picked<10?' *':''}</td></tr>`);
 const rr=data.relics.filter(matches).map(c=>`<tr><td title="${esc(c.id)}">${esc(c.name)}</td><td>${c.count}</td><td>${c.wins}</td><td class="${c.count<10?'muted':'positive'}">${num(c.rate)}%${c.count<10?' *':''}</td></tr>`);
 return `<div class="toolbar"><p>Выборы, которые формируют ваши колоды.</p><input id="search" type="search" placeholder="Найти карту или реликвию…" value="${esc(search)}" aria-label="Поиск карты"></div><div class="note">Это наблюдения, а не рейтинг силы. Для карт: один забег считается один раз, даже если карта предложена или взята несколько раз. Процент побед — среди забегов, где карту выбрали из награды. Реликвии — в финальном инвентаре. * Меньше 10 наблюдений. На результат влияют персонаж, сложность и длина забега.</div>${panel('Выбор карт',table(['Карта','Предложена, забегов','Взята, забегов','Частота выбора','Победы после выбора','% побед'],cr),'По частоте выбора')}${panel('Реликвии',table(['Реликвия','Забеги с реликвией','Победы','% побед'],rr),'По частоте в финальном инвентаре')}`;
}
function enemies(){
 return `<div class="note">Урон относится к вашему игроку, ходы — к комнате команды. Выберите одинаковую сложность для сравнения. Несколько боёв внутри одного узла показаны вместе.</div><div class="grid">${panel('Причины поражений',table(['Встреча / событие','Поражения'],data.causes.map(c=>`<tr><td>${esc(c.name)}</td><td class="negative">${c.count}</td></tr>`)))}${panel('Как читать статистику','<p class="help">Общий урон показывает, где суммарно теряется больше всего здоровья. Средний урон помогает сравнить отдельные встречи. Встречи с малым числом боёв дают нестабильные оценки. Число поражений относится только к явно записанной игре причине.</p>')}</div>${panel('Цена каждой встречи',table(['Встреча','Боёв','Всего урона','Урон / бой','Ходов / бой','Поражений'],data.enemies.map(e=>`<tr><td title="${esc(e.id)}">${esc(e.name)}</td><td>${e.combats}</td><td>${num(e.damage)}</td><td class="negative">${num(e.avg_damage)}</td><td>${num(e.avg_turns)}</td><td>${e.deaths}</td></tr>`)),'Сортировка по общему урону')}`;
}
function sources(){
 return panel('Данные остаются на компьютере',`<p class="help">Приложение читает JSON-файлы <b>*.run</b> из каталогов <b>profile*/saves/history</b>. Сохранения игры не изменяются. Обнаружение новых и изменённых файлов — каждые 15 секунд.</p><h3>Папка сохранений</h3><p class="source">${esc(meta.root)}</p><h3>Установленная игра: русский словарь</h3><p class="source">${esc(meta.pck||'Не найден; используются внутренние названия')}</p><p>${meta.names} названий. ${esc(meta.name_error)}</p><h3>Обнаруженные профили</h3>${table(['Профиль','Забегов'],meta.profiles.map(p=>`<tr><td>${esc(p.id)}</td><td>${p.count}</td></tr>`))}<div class="note">Победа берётся из поля win. Поражение — обычное завершение без победы либо признаки смерти (HP=0 при max HP>0, кроме перезапусков у Неоу). Звёздочка отмечает вывод по косвенным признакам, если was_abandoned=true. Записи у Неоу с флагом прерывания считаются перезапусками. «Прерван» — остальные прерывания. Фильтр «Исключить флаг прерван» исключает все записи с was_abandoned=true, в том числе со смертью. Процент побед = победы / все забеги текущей выборки.</div><p class="help">Для кооператива выбираются данные владельца Steam-профиля. Если его игрока нельзя определить, файл отображается в ошибках. Резервные копии не читаются. Копии одного забега внутри профиля не удваивают счётчик. Активный, ещё не завершённый забег появится после записи истории игрой.</p><h3>Ошибки чтения: ${meta.errors.length}</h3>${meta.errors.length?table(['Файл','Описание'],meta.errors.map(e=>`<tr><td class="source">${esc(e.file)}</td><td>${esc(e.error)}</td></tr>`)):'<p class="positive">Все найденные файлы истории успешно прочитаны.</p>'}`);
}
function render(){
 const titles={overview:'Каждый забег — опыт.',runs:'Ваш путь через Шпиль.',cards:'Что вы выбираете.',enemies:'Где Шпиль забирает своё.',sources:'Откуда берутся данные.'};
 $('#page-title').textContent=titles[tab];
 $('#subtitle').textContent=`${num(data.summary.count)} забегов в выборке · ${num(meta.total)} найдено на компьютере`;
 $('#content').innerHTML=data.summary.count||tab==='sources'?({overview, runs:history,cards,enemies,sources}[tab])():panel('Пока ничего не найдено','<div class="empty">Нет забегов с такими фильтрами. Измените профиль, режим, даты или сложность.</div>');
 document.querySelectorAll('[data-run]').forEach(el=>{el.onclick=()=>openRun(el.dataset.run);el.onkeydown=e=>{if(e.key==='Enter')openRun(el.dataset.run);};});
 if($('#search'))$('#search').oninput=e=>{const pos=e.target.selectionStart;search=e.target.value;page=0;render();$('#search').focus();$('#search').setSelectionRange(pos,pos);};
 if($('#prev'))$('#prev').onclick=()=>{page--;render();};if($('#next'))$('#next').onclick=()=>{page++;render();};
 $('#status').textContent=`${meta.errors.length?'⚠ '+meta.errors.length+' ошибок чтения · ':''}Обновлено ${new Date(meta.updated*1000).toLocaleTimeString('ru-RU')}`;
}
async function load(){
 const g=++generation;busy=true;
 try{const [m,d]=await Promise.all([api('/api/meta'),api('/api/analysis?'+query())]);if(g!==generation)return;meta=m;data=d;$('#error').classList.add('hidden');render();}
 catch(e){error(e);}finally{if(g===generation)busy=false;}
}
function hpChart(nodes){
 const valid=nodes.filter(n=>typeof n.hp==='number');if(!valid.length)return '<p>Нет истории здоровья.</p>';
 const W=950,H=155,p=12,max=Math.max(1,...valid.map(n=>n.max_hp||n.hp));
 const x=n=>p+(n.floor-1)*(W-2*p)/Math.max(1,nodes.length-1),y=n=>H-p-n.hp*(H-2*p)/max;
 return `<svg class="hp-chart" viewBox="0 0 ${W} ${H}" role="img" aria-label="Здоровье после каждого этажа"><line x1="${p}" x2="${W-p}" y1="${H-p}" y2="${H-p}" stroke="#46534b"/><polyline points="${valid.map(n=>`${x(n)},${y(n)}`).join(' ')}" fill="none" stroke="#b4d990" stroke-width="2"/>${valid.map(n=>`<circle cx="${x(n)}" cy="${y(n)}" r="3" fill="#b4d990"><title>Этаж ${n.floor}: ${n.hp}/${n.max_hp} HP · ${esc(n.room)}</title></circle>`).join('')}</svg><div class="caption">Здоровье после этажа · слева начало → справа завершение · наведите на точку</div>`;
}
async function openRun(id){
 try{const r=await api('/api/run/'+id);
 const deck=r.deck.map(c=>`<span class="chip" title="${esc(c.id)}">${esc(c.name)}${c.current_upgrade_level?'<b class="positive"> +'+c.current_upgrade_level+'</b>':''}<small> · этаж ${c.floor_added_to_deck??'?'}</small></span>`).join('');
 const relics=r.relics.map(c=>`<span class="chip" title="${esc(c.id)}">${esc(c.name)}</span>`).join('');
 const largest=[...r.nodes].filter(n=>n.damage>0).sort((a,b)=>b.damage-a.damage).slice(0,3);
 const notes=largest.map(n=>`<div class="insight">Этаж ${n.floor}, ${esc(n.room)}: ${n.damage} урона, ${n.turns} ходов.</div>`).join('');
 const rows=r.nodes.map(n=>{
  let choices=n.choices.map(c=>`<div class="${c.picked?'positive':'muted'}">${c.picked?'✓':'·'} ${esc(c.name)}</div>`).join('');
  if(n.gained.length)choices+=`<div>Получено: ${n.gained.map(esc).join(', ')}</div>`;
  if(n.removed.length)choices+=`<div class="negative">Удалено: ${n.removed.map(esc).join(', ')}</div>`;
  if(n.upgraded.length)choices+=`<div class="positive">Улучшено: ${n.upgraded.map(esc).join(', ')}</div>`;
  if(n.potions.length)choices+=`<div>Зелья: ${n.potions.map(esc).join(', ')}</div>`;
  if(n.relics.length)choices+=`<div>Реликвии: ${n.relics.map(esc).join(', ')}</div>`;
  if(n.rest.length)choices+=`<div>Костёр: ${n.rest.map(x=>esc(({HEAL:'Отдых',SMITH:'Улучшение'})[x]||x)).join(', ')}</div>`;
  return `<tr><td>${n.floor}<small class="muted"> · акт ${n.act}</small></td><td>${esc(types[n.type]||n.type)}<div class="muted">${esc(n.room)}</div></td><td>${n.hp??'—'}/${n.max_hp??'—'}</td><td class="${n.damage?'negative':''}">${n.damage}</td><td>${n.turns||'—'}</td><td>${n.gold??'—'}${n.spent?'<div class="muted">−'+n.spent+'</div>':''}</td><td class="node-choices">${choices||'—'}</td></tr>`;
 });
 $('#detail-content').innerHTML=`<h2 class="detail-title">${esc(r.character_name)} · A${r.ascension} ${badge(r)}</h2><p>${esc(r.date)} · ${Math.round(r.duration/60)} мин · ${r.coop?'Кооператив':'Одиночная игра'} · ${esc(r.version)}</p><p class="caption">Seed: ${esc(r.seed)} · ${esc(r.profile)}</p>${r.abandoned?'<div class="note">В истории стоит флаг «прерван». '+(r.outcome==='loss'?'Есть признаки смерти, поэтому результат предположительно показан как поражение (*).':'Результат определён по победе и признакам смерти.')+'</div>':''}${r.cause?'<p>Встреча при завершении: <b class="negative">'+esc(r.cause_name)+'</b></p>':''}<div class="small-stats"><span><b>${r.floors}</b> этажей</span><span><b>${r.damage}</b> урона получено</span><span><b>${r.elites}</b> элитных узлов</span><span><b>${r.potions_used}</b> зелий использовано</span><span><b>${r.spent}</b> золота потрачено</span></div>${panel('Здоровье на маршруте',hpChart(r.nodes))}${notes?panel('Где потеряно больше всего здоровья',notes):''}${r.outcome==='loss'&&r.potions.length?'<div class="note">После поражения остались зелья: '+r.potions.map(c=>esc(c.name)).join(', ')+'. Проверьте, могли ли они помочь до последнего боя.</div>':''}${panel('Финальная колода · '+r.deck.length,'<div class="chips">'+deck+'</div>')}${panel('Реликвии · '+r.relics.length,'<div class="chips">'+relics+'</div>')}${panel('Маршрут и решения',table(['Этаж','Комната','HP','Урон','Ходы','Золото','Выбор и действия'],rows))}<p class="caption source">${esc(r.source)}</p>`;
 if(!$('#detail').open)$('#detail').showModal();
 }catch(e){error(e);}
}
async function init(){
 try{
 meta=await api('/api/meta');
 $('#profile').innerHTML=meta.profiles.map(p=>`<option value="${esc(p.id)}">${esc(p.id)} · ${num(p.count)}</option>`).join('');$('#profile').value=meta.default_profile;
 $('#character').innerHTML+='<option disabled>─────────</option>'+meta.characters.map(c=>`<option value="${esc(c.id)}">${esc(c.name)}</option>`).join('');
 $('#version').innerHTML+=meta.versions.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
 for(const id of ids)$('#'+id).onchange=()=>{page=0;load();};
 document.querySelectorAll('[data-tab]').forEach(el=>el.onclick=()=>{tab=el.dataset.tab;page=0;search='';document.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('active',b===el));if(data)render();});
 $('#more').onclick=()=>$('#extra-filters').classList.toggle('hidden');$('#refresh').onclick=load;$('#close-detail').onclick=()=>$('#detail').close();
 await load();setInterval(()=>{if(!busy&&!$('#detail').open&&!$('#search')?.matches(':focus'))load();},15000);
 }catch(e){error(e);}
}
init();
