"""Native Windows desktop entry point. No browser or local web server required."""
import argparse
import csv
import ctypes
import datetime as dt
import json
import os
from pathlib import Path
import queue
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from analyzer import DEFAULT_ROOT, Store
from exports import csv_cell

VERSION = '1.1.0'
BG, PANEL, TEXT, MUTED, GREEN, RED = '#101619', '#1c252a', '#edf2ed', '#a0afb8', '#b4d990', '#f09388'
OUTCOMES = {'win': 'Победа', 'loss': 'Поражение', 'abandoned': 'Прерван'}
ROOMS = {'ancient':'Древний', 'monster':'Бой', 'elite':'Элита', 'boss':'Босс',
         'rest_site':'Костёр', 'shop':'Магазин', 'treasure':'Сокровище', 'unknown':'Событие', 'event':'Событие'}


def config_path(folder=None):
    default = Path.home() / 'Library/Application Support' if sys.platform == 'darwin' else Path(os.environ.get('LOCALAPPDATA', Path.home()))
    return Path(folder or default / 'SpireLens') / 'settings.json'


def load_config(path):
    try:
        result = json.loads(path.read_text(encoding='utf-8'))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_config(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def export_runs(store, query, path):
    fields = ['date','profile','character_name','ascension','mode','coop','outcome',
              'inferred','floors','duration','damage','deck_size','potions_used','cause_name','seed','version']
    with Path(path).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f, delimiter=';')
        writer.writerow(fields)
        for r in store.select(query):
            brief = store.brief(r)
            writer.writerow([csv_cell(brief[k]) for k in fields])


class Desktop:
    def __init__(self, root, config, args):
        self.root, self.config_file, self.args = root, config, args
        self.settings = load_config(config)
        self.store = None
        self.analysis = None
        self.events = queue.Queue()
        self.busy = False
        self.pending_filter = None
        self.profile_ids, self.character_ids = [], []
        self.current = {}
        root.title(f'SpireLens {VERSION} — Slay the Spire 2')
        root.geometry('1260x830')
        root.minsize(920, 650)
        root.configure(bg=BG)
        try:
            root.iconbitmap(str(Path(__file__).with_name('spirelens.ico')))
        except tk.TclError:
            pass
        root.protocol('WM_DELETE_WINDOW', self.close)
        root.report_callback_exception = self.callback_error
        self.style()
        self.build()
        self.root.after(100, self.poll)
        self.root.after(150, lambda: self.refresh(recreate=True))
        self.root.after(15000, self.auto_refresh)

    def style(self):
        s=ttk.Style(self.root);s.theme_use('clam')
        s.configure('.', background=BG, foreground=TEXT, font=('Segoe UI',10))
        s.configure('TFrame', background=BG)
        s.configure('Panel.TFrame', background=PANEL)
        s.configure('TLabel', background=BG, foreground=TEXT)
        s.configure('Muted.TLabel', foreground=MUTED)
        s.configure('Title.TLabel', font=('Segoe UI',25,'bold'),foreground=GREEN)
        s.configure('Metric.TLabel',font=('Segoe UI',25), background=PANEL, foreground=GREEN)
        s.configure('Panel.TLabel',background=PANEL,foreground=MUTED)
        s.configure('TButton',background='#2a383c',foreground=TEXT,padding=(12,8))
        s.map('TButton',background=[('active','#3d5148')])
        s.configure('TEntry',fieldbackground=PANEL,foreground=TEXT,insertcolor=TEXT)
        s.configure('TCombobox',fieldbackground=PANEL,background=PANEL,foreground=TEXT,arrowcolor=GREEN)
        s.map('TCombobox',fieldbackground=[('readonly',PANEL)],foreground=[('readonly',TEXT)])
        s.configure('TNotebook',background=BG,borderwidth=0)
        s.configure('TNotebook.Tab',background=PANEL,padding=(17,11),foreground=MUTED)
        s.map('TNotebook.Tab',background=[('selected','#2c3c30')],foreground=[('selected',GREEN)])
        s.configure('Treeview',background=PANEL,fieldbackground=PANEL,foreground=TEXT,rowheight=30,borderwidth=0)
        s.configure('Treeview.Heading',background='#273238',foreground=MUTED,padding=8)
        s.map('Treeview',background=[('selected','#3d5544')],foreground=[('selected',TEXT)])
        self.root.option_add('*TCombobox*Listbox.background',PANEL)
        self.root.option_add('*TCombobox*Listbox.foreground',TEXT)

    def build(self):
        outer=ttk.Frame(self.root,padding=22);outer.pack(fill='both',expand=True)
        header=ttk.Frame(outer);header.pack(fill='x',pady=(0,15))
        ttk.Label(header,text='◈  SpireLens',style='Title.TLabel').pack(side='left')
        ttk.Button(header,text='Папка сохранений',command=self.choose_folder).pack(side='right',padx=5)
        ttk.Button(header,text='Файл игры / названия',command=self.choose_pck).pack(side='right',padx=5)
        self.refresh_button=ttk.Button(header,text='↻ Обновить',command=self.refresh);self.refresh_button.pack(side='right',padx=5)
        self.subtitle=tk.StringVar(value='Личный дневник восхождений · данные остаются на компьютере')
        ttk.Label(outer,textvariable=self.subtitle,style='Muted.TLabel').pack(anchor='w',pady=(0,12))
        filters=ttk.Frame(outer);filters.pack(fill='x',pady=(0,8))
        self.vars={}
        specs=[('profile','Steam-профиль',[],29),('character','Персонаж',['Все'],19),
               ('ascension','Вознесение',['Все']+[f'A{i}' for i in range(21)],10),
               ('mode','Режим',['Обычный','Все','Ежедневный','Особый'],13),
               ('party','Команда',['Одиночная','Кооператив','Все'],13)]
        self.combos={}
        for i,(key,label,values,width) in enumerate(specs):
            box=ttk.Frame(filters);box.grid(row=0,column=i,sticky='ew',padx=(0,10))
            ttk.Label(box,text=label,style='Muted.TLabel').pack(anchor='w')
            var=tk.StringVar(value=values[0] if values else '');self.vars[key]=var
            combo=ttk.Combobox(box,textvariable=var,values=values,state='readonly',width=width)
            combo.pack(fill='x',pady=(4,0));combo.bind('<<ComboboxSelected>>',self.filter_changed);self.combos[key]=combo
        extra=ttk.Frame(outer);extra.pack(fill='x',pady=(0,14))
        for i,(key,label,width) in enumerate([('outcome','Результат',23),('from','С даты ГГГГ-ММ-ДД',17),('to','По дату',17),('min_floor','Минимальный этаж',16)]):
            box=ttk.Frame(extra);box.grid(row=0,column=i,sticky='w',padx=(0,12))
            ttk.Label(box,text=label,style='Muted.TLabel').pack(anchor='w')
            self.vars[key]=tk.StringVar(value='Все' if key=='outcome' else '0' if key=='min_floor' else '')
            if key=='outcome':
                c=ttk.Combobox(box,textvariable=self.vars[key],values=['Все','Победы и поражения (*)','Победа','Поражение','Прерван'],state='readonly',width=width)
                c.bind('<<ComboboxSelected>>',self.filter_changed)
            else:
                c=ttk.Entry(box,textvariable=self.vars[key],width=width);c.bind('<Return>',self.filter_changed);c.bind('<FocusOut>',self.filter_changed)
            c.pack(pady=(4,0))
        ttk.Button(extra,text='Применить',command=self.filter_changed).grid(row=0,column=4,sticky='s')
        self.book=ttk.Notebook(outer);self.book.pack(fill='both',expand=True)
        self.pages={}
        for key,label in [('overview','Обзор'),('runs','История'),('cards','Карты'),('relics','Реликвии'),('enemies','Встречи'),('sources','Источники')]:
            frame=ttk.Frame(self.book,padding=14);self.book.add(frame,text=label);self.pages[key]=frame
        self.build_overview()
        self.search=tk.StringVar();toolbar=ttk.Frame(self.pages['runs']);toolbar.pack(fill='x',pady=(0,10))
        ttk.Label(toolbar,text='Поиск:').pack(side='left')
        entry=ttk.Entry(toolbar,textvariable=self.search,width=40);entry.pack(side='left',padx=10)
        self.search.trace_add('write',lambda *_:self.render_history())
        ttk.Button(toolbar,text='Экспорт CSV',command=self.export).pack(side='right')
        ttk.Label(self.pages['runs'],text='Двойной щелчок или Enter — открыть разбор. * Поражение по косвенным признакам.',style='Muted.TLabel').pack(anchor='w',pady=(0,10))
        self.history=self.table(self.pages['runs'],['Дата','Персонаж','A','Итог','Этаж','Мин','Карт','Встреча при завершении'],[140,140,45,115,55,60,55,220])
        self.history.bind('<Double-1>',self.open_selected);self.history.bind('<Return>',self.open_selected)
        ttk.Label(self.pages['cards'],text='Каждый забег считается один раз. % побед — среди выбравших карту; это связь с исходом, а не рейтинг силы. * Менее 10 выборов.',style='Muted.TLabel',wraplength=1050).pack(anchor='w',pady=(0,12))
        self.cards=self.table(self.pages['cards'],['Карта','Предложена, забегов','Взята, забегов','Выбор, %','Побед','Победы, %'],[270,160,150,110,100,110])
        ttk.Label(self.pages['relics'],text='Реликвии в финальном инвентаре. Длинные забеги имеют больше возможностей получить реликвии. * Менее 10 наблюдений.',style='Muted.TLabel',wraplength=1050).pack(anchor='w',pady=(0,12))
        self.relics=self.table(self.pages['relics'],['Реликвия','Забеги','Победы','Победы, %'],[380,130,130,140])
        ttk.Label(self.pages['enemies'],text='Урон — вашего игрока; ходы — комнаты команды. Нажмите заголовок, чтобы изменить сортировку.',style='Muted.TLabel').pack(anchor='w',pady=(0,12))
        self.enemies=self.table(self.pages['enemies'],['Встреча','Боёв','Общий урон','Урон / бой','Ходы / бой','Поражения'],[350,100,130,130,130,120])
        self.sources=self.textbox(self.pages['sources'])
        self.status=tk.StringVar(value='Загрузка истории…')
        ttk.Label(outer,textvariable=self.status,style='Muted.TLabel').pack(anchor='w',pady=(12,0))

    def build_overview(self):
        frame=self.pages['overview'];metrics=ttk.Frame(frame);metrics.pack(fill='x',pady=(0,15));self.metrics=[]
        for i,label in enumerate(['ПОБЕДЫ','СРЕДНИЙ ЭТАЖ','ЧАСОВ В ЗАБЕГАХ','ПОРАЖЕНИЯ / ПРЕРВАНЫ']):
            box=ttk.Frame(metrics,padding=14,style='Panel.TFrame');box.grid(row=0,column=i,sticky='ew',padx=(0,9));metrics.columnconfigure(i,weight=1)
            ttk.Label(box,text=label,style='Panel.TLabel',font=('Segoe UI',9)).pack(anchor='w')
            var=tk.StringVar(value='—');self.metrics.append(var);ttk.Label(box,textvariable=var,style='Metric.TLabel').pack(anchor='w',pady=(7,0))
        ttk.Label(frame,text='Последние 80 забегов · высота точки = этаж · светлые точки = победы',style='Muted.TLabel').pack(anchor='w')
        self.trend=tk.Canvas(frame,height=125,bg=PANEL,highlightthickness=0);self.trend.pack(fill='x',pady=(7,12));self.trend.bind('<Configure>',lambda _:self.draw_trend())
        self.insights=tk.StringVar(value='Загружаем наблюдения…')
        ttk.Label(frame,textvariable=self.insights,wraplength=1100,justify='left').pack(anchor='w',pady=(0,14))
        self.characters=self.table(frame,['Персонаж','Забегов','Побед','Победы, %','Средний этаж'],[260,140,140,150,150],height=5)

    def table(self,parent,headers,widths,height=14):
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True)
        columns=[str(i) for i in range(len(headers))]
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=height,selectmode='browse')
        for cid,title,width in zip(columns,headers,widths):
            tree.heading(cid,text=title,command=lambda c=cid:self.sort_table(tree,c))
            tree.column(cid,width=width,minwidth=45,anchor='w')
        y=ttk.Scrollbar(frame,orient='vertical',command=tree.yview);x=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=y.set,xscrollcommand=x.set)
        tree.grid(row=0,column=0,sticky='nsew');y.grid(row=0,column=1,sticky='ns');x.grid(row=1,column=0,sticky='ew')
        frame.rowconfigure(0,weight=1);frame.columnconfigure(0,weight=1)
        tree.tag_configure('win',foreground=GREEN);tree.tag_configure('loss',foreground=RED);tree.tag_configure('abandoned',foreground=MUTED)
        return tree

    @staticmethod
    def sort_table(tree,column):
        reverse=getattr(tree,'last_sort',None)==(column,False)
        def key(row):
            text=tree.set(row,column).rstrip('% *').removeprefix('A').strip()
            try:return (0,float(text.replace(',','.')))
            except ValueError:
                try:return (0,dt.datetime.strptime(text,'%d.%m.%Y %H:%M').timestamp())
                except ValueError:return (1,text.casefold())
        for index,row in enumerate(sorted(tree.get_children(),key=key,reverse=reverse)):tree.move(row,'',index)
        tree.last_sort=(column,reverse)

    @staticmethod
    def textbox(parent):
        text=tk.Text(parent,bg=PANEL,fg=TEXT,insertbackground=TEXT,font=('Segoe UI',11),wrap='word',padx=16,pady=15,relief='flat')
        scroll=ttk.Scrollbar(parent,command=text.yview);text.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right',fill='y');text.pack(fill='both',expand=True);text.configure(state='disabled');return text

    @staticmethod
    def set_text(widget,text):
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',text);widget.configure(state='disabled')

    def query(self):
        v={k:x.get().strip() for k,x in self.vars.items()}
        return dict(profile=self.current.get('profile',''),character=self.current.get('character',''),
            ascension='' if v['ascension']=='Все' else v['ascension'].removeprefix('A'),
            mode={'Обычный':'standard','Ежедневный':'daily','Особый':'custom','Все':''}[v['mode']],
            party={'Одиночная':'solo','Кооператив':'coop','Все':''}[v['party']],
            outcome={'Все':'','Победы и поражения (*)':'finished','Победа':'win','Поражение':'loss','Прерван':'abandoned'}[v['outcome']],
            **{'from':v['from'],'to':v['to'],'min_floor':v['min_floor'] or '0'})

    def filter_changed(self,event=None):
        for key,values in [('profile',self.profile_ids),('character',self.character_ids)]:
            index=self.combos[key].current()
            if 0<=index<len(values):self.current[key]=values[index]
        if self.store:
            if self.pending_filter:self.root.after_cancel(self.pending_filter)
            self.pending_filter=self.root.after(150,self.analyze)

    def analyze(self):
        self.pending_filter=None
        try:
            self.analysis=self.store.analysis(self.query());self.render()
        except (ValueError,OSError) as e:
            self.status.set(str(e))

    def refresh(self,recreate=False):
        if self.busy:return
        self.busy=True;self.refresh_button.configure(state='disabled');self.status.set('Чтение истории забегов…')
        root_path=self.args.data_dir or self.settings.get('data_dir') or str(DEFAULT_ROOT)
        pck=self.args.pck or self.settings.get('pck') or None
        old=self.store
        def work():
            try:
                store=Store(root_path,pck) if recreate or old is None else old
                store.refresh();self.events.put(('loaded',store))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=work,daemon=True).start()

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait();self.busy=False;self.refresh_button.configure(state='normal')
                if kind=='error':self.status.set(value);continue
                self.store=value;meta=value.metadata()
                profile=self.current.get('profile') or meta['default_profile']
                self.profile_ids=[p['id'] for p in meta['profiles']]
                self.combos['profile']['values']=[f'{p["id"]} · {p["count"]}' for p in meta['profiles']]
                if profile in self.profile_ids:self.combos['profile'].current(self.profile_ids.index(profile));self.current['profile']=profile
                elif self.profile_ids:self.combos['profile'].current(0);self.current['profile']=self.profile_ids[0]
                else:self.vars['profile'].set('История не найдена');self.current['profile']=''
                char=self.current.get('character','');self.character_ids=['']+[p['id'] for p in meta['characters']]
                self.combos['character']['values']=['Все']+[p['name'] for p in meta['characters']]
                self.combos['character'].current(self.character_ids.index(char) if char in self.character_ids else 0)
                self.current['character']=char if char in self.character_ids else ''
                self.analyze()
                if self.args.smoke_test:self.root.after(100,self.smoke_finish)
        except queue.Empty:pass
        self.root.after(100,self.poll)

    def render(self):
        a=self.analysis;s=a['summary'];meta=self.store.metadata()
        self.subtitle.set(f'{s["count"]:,} забегов в выборке · {meta["total"]:,} найдено · локально, без интернета'.replace(',',' '))
        for var,text in zip(self.metrics,[f'{s["rate"]}% · {s["wins"]} побед',str(s['avg_floor']),str(s['hours']),f'{s["losses"]} / {s["abandoned"]}']):var.set(text)
        self.insights.set('\n\n'.join('↗  '+x for x in a['insights'][:3]) or 'История пока пуста. Нажмите «Папка сохранений» и выберите каталог SlayTheSpire2 или history.')
        self.fill(self.characters,[(c['name'],c['count'],c['wins'],c['rate'],c['floors']) for c in a['characters']])
        self.render_history()
        self.fill(self.cards,[(c['name'],c['offered'],c['picked'],c['pick_rate'],c['wins'],('—' if c['rate'] is None else str(c['rate'])+('% *' if c['picked']<10 else '%'))) for c in a['cards']])
        self.fill(self.relics,[(c['name'],c['count'],c['wins'],str(c['rate'])+('% *' if c['count']<10 else '%')) for c in a['relics']])
        self.fill(self.enemies,[(c['name'],c['combats'],c['damage'],c['avg_damage'],c['avg_turns'],c['deaths']) for c in a['enemies']])
        explanation=('SpireLens '+VERSION+' · Windows x64\n\nПапка истории:\n'+meta['root']+'\n\nФайл игры для русских названий:\n'+(meta['pck'] or 'Не найден; нажмите «Файл игры / названия»')+f'\n\nПрочитано {meta["total"]} забегов и {meta["names"]} русских названий.\n\n'+
            'Приложение только читает *.run в каталогах history. Сохранения не изменяются и не передаются в интернет. Новые завершённые забеги обнаруживаются каждые 15 секунд.\n\n'+
            'Победа: win=true. Поражение: обычное завершение без победы. При флаге was_abandoned=true и HP=0 при max_hp>0 поражение определяется предположительно и отмечается *. Перезапуски у Неоу считаются прерываниями. Поле killed_by само по себе не доказывает смерть.\n\n'+
            'Процент побед = победы / все забеги выборки, включая прерывания. Выберите «Победы и поражения (*)», чтобы исключить прерывания без признаков смерти.\n\n'+
            'В кооперативе анализируется владелец Steam-профиля. Копии одного забега внутри профиля не удваиваются. Этаж — посещённый узел, включая Древнего.\n\n'+
            'Карты: частота выбора из награды, каждый забег один раз. Это наблюдения, а не рейтинг силы. Реликвии считаются в финальном инвентаре. Полного порядка розыгрыша карт история не содержит.\n\n'+
            'Настройки этого компьютера:\n'+str(self.config_file)+'\n\n'+
            f'Ошибок чтения: {len(meta["errors"])}\n'+ '\n'.join(e['file']+'\n'+e['error'] for e in meta['errors'])+ ('\nСловарь: '+meta['name_error'] if meta['name_error'] else ''))
        self.set_text(self.sources,explanation);self.draw_trend()
        self.status.set(f'Обновлено {dt.datetime.now():%H:%M:%S} · {s["count"]} забегов · ошибок: {len(meta["errors"])} · двойной щелчок по истории — разбор')

    @staticmethod
    def fill(tree,rows):
        tree.delete(*tree.get_children())
        for row in rows:tree.insert('','end',values=row)

    def render_history(self):
        if not self.analysis:return
        selection=self.history.selection();selected=selection[0] if selection else ''
        self.history.delete(*self.history.get_children());term=self.search.get().casefold()
        for r in self.analysis['runs']:
            if term and not any(term in str(r[k]).casefold() for k in ('date','character_name','cause_name','seed')):continue
            self.history.insert('','end',iid=r['id'],tags=(r['outcome'],),values=(r['date'],r['character_name'],r['ascension'],OUTCOMES[r['outcome']]+(' *' if r['inferred'] else ''),r['floors'],round(r['duration']/60,1),r['deck_size'],r['cause_name']))
        if self.history.exists(selected):self.history.selection_set(selected)

    def draw_trend(self):
        if not self.analysis:return
        canvas=self.trend;canvas.delete('all');items=self.analysis['trend']
        if not items:return
        width=max(100,canvas.winfo_width());height=max(80,canvas.winfo_height());maximum=max(10,max(r['floors'] for r in items))
        coords=[]
        for index,r in enumerate(items):
            x=12+index*(width-24)/max(1,len(items)-1);y=height-12-r['floors']*(height-24)/maximum;coords.extend((x,y))
        if len(coords)>=4:canvas.create_line(*coords,fill='#718c73',width=2)
        for i,r in enumerate(items):
            x,y=coords[2*i:2*i+2];radius=4 if r['win'] else 2
            canvas.create_oval(x-radius,y-radius,x+radius,y+radius,fill=GREEN if r['win'] else MUTED,outline='')

    def open_selected(self,event=None):
        ids=self.history.selection()
        if ids:self.open_run(ids[0])

    def open_run(self,identifier):
        r=self.store.detail(identifier)
        if not r:return
        w=tk.Toplevel(self.root);w.title(f'{r["character_name"]} · A{r["ascension"]} · {r["date"]}');w.geometry('1120x760');w.configure(bg=BG)
        frame=ttk.Frame(w,padding=20);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text=f'{r["character_name"]} · A{r["ascension"]} · {OUTCOMES[r["outcome"]]}'+(' *' if r['inferred'] else ''),font=('Segoe UI',21,'bold'),foreground=GREEN).pack(anchor='w')
        ttk.Label(frame,text=f'{r["date"]} · {round(r["duration"]/60,1)} мин · {r["floors"]} этажей · {r["damage"]} урона · Seed: {r["seed"]}',style='Muted.TLabel').pack(anchor='w',pady=8)
        notes=f'Встреча при завершении: {r["cause_name"]}. '
        if r['inferred']:notes+='* Поражение предположительно определено по нулевому HP; исходный флаг игры — «прерван». '
        if r['outcome']=='loss' and r['potions']:notes+='Остались зелья: '+', '.join(c['name'] for c in r['potions'])+'.'
        ttk.Label(frame,text=notes,wraplength=1050,foreground=MUTED).pack(anchor='w',pady=(0,10))
        chart=tk.Canvas(frame,height=100,bg=PANEL,highlightthickness=0);chart.pack(fill='x',pady=(0,12))
        def draw(_=None):
            chart.delete('all');nodes=[n for n in r['nodes'] if isinstance(n['hp'],(int,float))];points=[]
            maximum=max([1]+[n['max_hp'] or n['hp'] for n in nodes]);width=max(100,chart.winfo_width())
            for n in nodes:points.extend((12+(n['floor']-1)*(width-24)/max(1,r['floors']-1),87-n['hp']*65/maximum))
            if len(points)>=4:chart.create_line(*points,fill=GREEN,width=2)
            chart.create_text(12,12,text='Здоровье после каждого этажа',fill=MUTED,anchor='w')
        chart.bind('<Configure>',draw)
        book=ttk.Notebook(frame);book.pack(fill='both',expand=True)
        route=ttk.Frame(book,padding=10);deck=ttk.Frame(book,padding=10);relics=ttk.Frame(book,padding=10);review=ttk.Frame(book,padding=10)
        for f,title in [(route,'Маршрут и решения'),(deck,f'Колода · {len(r["deck"])}'),(relics,f'Реликвии · {len(r["relics"])}'),(review,'Разбор')]:book.add(f,text=title)
        tree=self.table(route,['Этаж','Комната','HP','Урон','Ходы','Золото','Выбор / действия'],[60,230,75,65,65,70,440])
        for n in r['nodes']:
            actions=['✓ '+c['name'] if c['picked'] else '· '+c['name'] for c in n['choices']]
            for key,label in [('gained','Получено'),('removed','Удалено'),('upgraded','Улучшено'),('potions','Зелья'),('relics','Реликвии'),('rest','Костёр')]:
                if n[key]:actions.append(label+': '+', '.join(n[key]))
            tree.insert('','end',iid=str(n['floor']),values=(n['floor'],n['room'],f'{n["hp"]}/{n["max_hp"]}',n['damage'],n['turns'],n['gold'],' | '.join(actions)))
        def room_detail(_=None):
            selection=tree.selection()
            if selection:
                node=next(n for n in r['nodes'] if n['floor']==int(selection[0]))
                lines=[f'Здоровье: {node["hp"]}/{node["max_hp"]}',f'Получено урона: {node["damage"]}',f'Ходов: {node["turns"]}',f'Золото: {node["gold"]}',f'Потрачено: {node["spent"]}', '', 'Предложенные карты:']
                lines += [('✓ Взята: ' if c['picked'] else 'Пропущена: ')+c['name'] for c in node['choices']]
                for key,label in [('gained','Получено'),('removed','Удалено'),('upgraded','Улучшено'),('potions','Использованы зелья'),('relics','Реликвии'),('rest','Костёр')]:
                    if node[key]:lines.append(label+': '+', '.join(node[key]))
                messagebox.showinfo(f'Этаж {node["floor"]} · {node["room"]}','\n'.join(lines),parent=w)
        tree.bind('<Double-1>',room_detail)
        self.fill(self.table(deck,['Карта','Улучшение','Получена на этаже'],[400,150,180]),[(c['name'],c.get('current_upgrade_level',0),c.get('floor_added_to_deck','—')) for c in r['deck']])
        self.fill(self.table(relics,['Реликвия','Получена на этаже'],[500,180]),[(c['name'],c.get('floor_added_to_deck','—')) for c in r['relics']])
        worst=sorted(r['nodes'],key=lambda n:n['damage'],reverse=True)[:5]
        text='Где потеряно больше всего здоровья\n\n'+'\n\n'.join(f'Этаж {n["floor"]}: {n["room"]} — {n["damage"]} урона, {n["turns"]} ходов.' for n in worst if n['damage'])
        text+='\n\nЗелий использовано: '+str(r['potions_used'])+'\nЗолота потрачено: '+str(r['spent'])+'\nЭлитных узлов: '+str(r['elites'])+'\n\nИсточник:\n'+r['source']
        self.set_text(self.textbox(review),text)
        return w

    def choose_folder(self):
        if self.busy:return
        path=filedialog.askdirectory(title='Папка SlayTheSpire2, Steam-профиля или history',initialdir=str(DEFAULT_ROOT if DEFAULT_ROOT.exists() else Path.home()))
        if path:self.settings['data_dir']=path;self.args.data_dir=None;self.persist();self.current={};self.refresh(recreate=True)

    def choose_pck(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='Выберите SlayTheSpire2.pck из установленной игры',filetypes=[('Пакет игры','*.pck')])
        if path:self.settings['pck']=path;self.args.pck=None;self.persist();self.refresh(recreate=True)

    def persist(self):
        try:save_config(self.config_file,self.settings)
        except OSError as e:messagebox.showerror('Настройки',str(e),parent=self.root)

    def export(self):
        if not self.store:return
        path=filedialog.asksaveasfilename(title='Экспорт текущей выборки',initialfile='SpireLens-runs.csv',defaultextension='.csv',filetypes=[('CSV для Excel','*.csv')])
        if path:
            try:export_runs(self.store,self.query(),path);self.status.set('Экспорт сохранён: '+path)
            except OSError as e:messagebox.showerror('Экспорт',str(e),parent=self.root)

    def auto_refresh(self):
        # Leave tables stable while the user is inspecting a run in a child window.
        if not any(isinstance(w,tk.Toplevel) for w in self.root.winfo_children()):self.refresh()
        self.root.after(15000,self.auto_refresh)

    def smoke_finish(self):
        try:
            assert self.store is not None and self.analysis is not None
            for page in self.pages.values():self.book.select(page);self.root.update_idletasks()
            if self.analysis['runs']:
                w=self.open_run(self.analysis['runs'][0]['id']);self.root.update_idletasks();w.destroy()
            result={'version':VERSION,'frozen':bool(getattr(sys,'frozen',False)),'python':sys.version,
                    'total':len(self.store.runs),'errors':self.store.errors,'filtered':self.analysis['summary']['count'],
                    'native_window':True,'tabs':list(self.pages),'names':len(self.store.names)}
            if self.args.report:
                Path(self.args.report).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                export_runs(self.store,self.query(),Path(self.args.report).with_suffix('.csv'))
            self.root.destroy()
        except Exception as e:
            if self.args.report:Path(self.args.report).write_text(json.dumps({'error':str(e)}),encoding='utf-8')
            self.root.destroy();raise

    def callback_error(self,kind,value,tb):
        import traceback
        if self.args.smoke_test:
            if self.args.report:Path(self.args.report).write_text(json.dumps({'error':str(value)}),encoding='utf-8')
            self.root.destroy()
        else:messagebox.showerror('SpireLens',str(value),parent=self.root)
        traceback.print_exception(kind,value,tb,file=sys.stderr)

    def close(self):
        self.root.destroy()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data-dir');parser.add_argument('--pck');parser.add_argument('--config-dir')
    parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--report')
    args=parser.parse_args()
    mutex=None
    if sys.platform=='win32':
        try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError,AttributeError):pass
        try:ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID('SpireLens.Desktop.1')
        except (OSError,AttributeError):pass
        ctypes.windll.kernel32.CreateMutexW.restype=ctypes.c_void_p
        mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'SpireLensDesktop')
    try:
        root=tk.Tk();Desktop(root,config_path(args.config_dir),args);root.mainloop()
    finally:
        if mutex:
            ctypes.windll.kernel32.CloseHandle.argtypes=[ctypes.c_void_p]
            ctypes.windll.kernel32.CloseHandle(mutex)


if __name__=='__main__':main()
