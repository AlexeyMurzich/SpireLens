"""Read-only Slay the Spire 2 history adapter and analysis (standard library)."""
import collections
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import threading
import time

if sys.platform == 'darwin':
    DEFAULT_ROOT = Path.home() / 'Library/Application Support/SlayTheSpire2'
else:
    DEFAULT_ROOT = Path(os.environ.get('APPDATA', Path.home() / 'AppData/Roaming')) / 'SlayTheSpire2'
# The macOS build ships the pack inside the app bundle under a different file name.
PCK_PATHS = ('steamapps/common/Slay the Spire 2/SlayTheSpire2.pck',
             'steamapps/common/Slay the Spire 2/SlayTheSpire2.app/Contents/Resources/Slay the Spire 2.pck')


def number(value, default=0):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else default


def model_id(value):
    return str(value.get('id', '')) if isinstance(value, dict) else str(value or '')


def normalize(data, path, root):
    if not isinstance(data, dict) or not isinstance(data.get('players'), list) or not data['players']:
        raise ValueError('Нет списка игроков: неизвестный формат истории')
    rel = path.relative_to(root).as_posix()
    parts = path.parts
    profile = next((p for p in reversed(parts[:-1]) if re.fullmatch(r'profile\d+', p)), 'profile1')
    account = next((p for p in parts if re.fullmatch(r'\d{15,20}', p)), 'local')
    players = data['players']
    player = next((p for p in players if str(p.get('id')) == account), None)
    if player is None and len(players) == 1:
        player = players[0]
    if player is None:
        raise ValueError('В кооперативном забеге не найден владелец профиля')
    pid = str(player.get('id'))
    nodes = []
    for act_index, act in enumerate(data.get('map_point_history', []), 1):
        if not isinstance(act, list):
            raise ValueError('Неизвестный формат маршрута')
        for node in act:
            stats = next((s for s in node.get('player_stats', []) if str(s.get('player_id')) == pid), {})
            rooms = node.get('rooms', [])
            encounters = [r.get('model_id', '') for r in rooms if r.get('room_type') in ('monster', 'elite', 'boss')]
            nodes.append(dict(floor=len(nodes) + 1, act=act_index,
                type=node.get('map_point_type', 'unknown'), stats=stats,
                rooms=rooms, encounter=' / '.join(encounters),
                turns=sum(number(r.get('turns_taken')) for r in rooms)))
    start = number(data.get('start_time'))
    dt.datetime.fromtimestamp(start)  # Reject invalid timestamps before they reach filters/UI.
    last = nodes[-1]['stats'] if nodes else {}
    win = data.get('win') is True
    abandoned = data.get('was_abandoned') is True
    cause = next((data.get(k) for k in ('killed_by_encounter', 'killed_by_event')
                  if data.get(k) and data[k] != 'NONE.NONE'), '')
    # NEOW + zeroed stats is a common first-room restart, not evidence of combat death.
    dead_hp = number(last.get('current_hp'), 1) <= 0 and number(last.get('max_hp')) > 0
    death = not win and cause != 'EVENT.NEOW' and dead_hp
    outcome = 'win' if win else 'loss' if death or not abandoned else 'abandoned'
    inferred = outcome == 'loss' and abandoned
    return dict(id=hashlib.sha256(rel.encode()).hexdigest()[:24], source=str(path),
        profile=f'{account}/{profile}', account=account, profile_name=profile,
        character=player.get('character', 'UNKNOWN'), ascension=number(data.get('ascension')),
        mode=data.get('game_mode', 'unknown'), coop=len(players) > 1,
        start=start, duration=number(data.get('run_time')), version=data.get('build_id', '?'),
        schema=data.get('schema_version'), seed=str(data.get('seed', '')),
        win=win, abandoned=abandoned, outcome=outcome, inferred=inferred, cause=cause,
        floors=len(nodes), deck=player.get('deck', []), relics=player.get('relics', []),
        potions=player.get('potions', []), nodes=nodes,
        damage=sum(number(n['stats'].get('damage_taken')) for n in nodes),
        spent=sum(number(n['stats'].get('gold_spent')) for n in nodes),
        potions_used=sum(len(n['stats'].get('potion_used', [])) for n in nodes),
        elites=sum(n['type'] == 'elite' for n in nodes))


def read_names(pck):
    """Read only title strings from an unencrypted Godot PCK v2/v3.

    Format reference: https://github.com/godotengine/godot/blob/4.5/core/io/file_access_pack.cpp
    """
    result = {}
    tables = {'cards': 'CARD', 'relics': 'RELIC', 'potions': 'POTION',
              'characters': 'CHARACTER', 'encounters': 'ENCOUNTER', 'events': 'EVENT', 'acts': 'ACT'}
    with Path(pck).open('rb') as f:
        if f.read(4) != b'GDPC':
            raise ValueError('Неверный заголовок PCK')
        version, major, minor, patch, flags = struct.unpack('<IIIII', f.read(20))
        if version not in (2, 3) or flags & 1:
            raise ValueError('Не поддерживается версия или шифрование PCK')
        base = struct.unpack('<Q', f.read(8))[0]
        if version == 3:
            f.seek(struct.unpack('<Q', f.read(8))[0])
        else:
            f.read(64)
        count = struct.unpack('<I', f.read(4))[0]
        if count > 1000000:
            raise ValueError('Некорректный каталог PCK')
        entries = []
        for _ in range(count):
            length = struct.unpack('<I', f.read(4))[0]
            if length > 16384:
                raise ValueError('Некорректный путь PCK')
            name = f.read(length).rstrip(b'\0').decode('utf-8').removeprefix('res://')
            offset, size = struct.unpack('<QQ', f.read(16))
            f.read(16)
            entry_flags = struct.unpack('<I', f.read(4))[0]
            table = Path(name).stem
            if name.startswith('localization/rus/') and table in tables and not entry_flags & 3 and size < 5000000:
                entries.append((table, base + offset, size))
        for table, offset, size in entries:
            f.seek(offset)
            data = json.loads(f.read(size))
            for key, value in data.items():
                if key.endswith('.title') and isinstance(value, str):
                    result[f'{tables[table]}.{key[:-6]}'] = re.sub(r'\[/?[^\]]+\]', '', value)
    return result


def find_pck():
    bases = [Path(os.environ.get('PROGRAMFILES(X86)', 'C:/Program Files (x86)')) / 'Steam',
             Path.home() / 'Library/Application Support/Steam']
    if os.name == 'nt':
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
                bases.append(Path(winreg.QueryValueEx(key, 'SteamPath')[0]))
        except OSError:
            pass
    for steam_root in list(bases):
        try:
            vdf = steam_root / 'steamapps/libraryfolders.vdf'
            bases += [Path(p.replace('\\\\', '\\')) for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding='utf-8'))]
        except OSError:
            pass
    return next((p for b in bases for name in PCK_PATHS if (p := b / name).is_file()), None)


class Store:
    def __init__(self, root=DEFAULT_ROOT, pck=None):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.cache = {}
        self.runs = []
        self.errors = []
        self.updated = 0
        self.names = {}
        self.name_error = ''
        self.pck = pck or find_pck()
        if self.pck:
            try:
                self.names = read_names(self.pck)
            except (OSError, ValueError, struct.error, UnicodeError) as e:
                self.name_error = str(e)

    def refresh(self):
        with self.lock:
            errors, current = [], {}
            paths = self.root.rglob('*.run') if self.root.exists() else []
            for path in paths:
                # Only completed history; backups and crash telemetry are not data sources.
                if path.parent.name != 'history':
                    continue
                try:
                    st = path.stat()
                    signature = (st.st_mtime_ns, st.st_size)
                    old = self.cache.get(str(path))
                    if old and old[0] == signature:
                        current[str(path)] = old
                        continue
                    if st.st_size > 20_000_000:
                        raise ValueError('Слишком большой файл истории')
                    data = json.loads(path.read_text(encoding='utf-8-sig'))
                    run = normalize(data, path, self.root)
                    current[str(path)] = (signature, run)
                except (OSError, ValueError, TypeError, KeyError, AttributeError, OverflowError) as e:
                    errors.append(dict(file=str(path), error=str(e)))
            self.cache = current
            # A copied backup of the same run inside one profile must not inflate statistics.
            seen, runs = set(), []
            for _, run in current.values():
                key = (run['profile'], run['start'], run['seed'], run['character'], run['mode'], run['coop'])
                if key not in seen:
                    seen.add(key)
                    runs.append(run)
            self.runs = sorted(runs, key=lambda r: r['start'], reverse=True)
            self.errors = errors
            self.updated = time.time()

    def name(self, identifier):
        if not identifier:
            return '—'
        if ' / ' in identifier:
            return ' / '.join(self.name(x) for x in identifier.split(' / '))
        return self.names.get(identifier, identifier.split('.')[-1].replace('_', ' ').title())

    def metadata(self):
        with self.lock:
            profiles = collections.Counter(r['profile'] for r in self.runs)
            return dict(root=str(self.root), pck=str(self.pck or ''), names=len(self.names),
                name_error=self.name_error, errors=self.errors, total=len(self.runs), updated=self.updated,
                profiles=[dict(id=k, count=v) for k, v in profiles.items()],
                default_profile=self.runs[0]['profile'] if self.runs else '',
                characters=[dict(id=c, name=self.name(c)) for c in sorted({r['character'] for r in self.runs})],
                versions=sorted({r['version'] for r in self.runs}, reverse=True))

    def select(self, query):
        def get(k, default=''):
            v = query.get(k, [default])
            return v[0] if isinstance(v, list) else v
        asc = get('ascension')
        minimum = get('min_floor', '0')
        try:
            asc = int(asc) if asc else None
            minimum = max(0, int(minimum))
            dates = [dt.date.fromisoformat(get(k)) if get(k) else None for k in ('from', 'to')]
        except ValueError as e:
            raise ValueError('Проверьте сложность, этаж и даты фильтра') from e
        with self.lock:
            chosen = []
            for r in self.runs:
                if any(get(k) and r[k] != get(k) for k in ('profile', 'character', 'mode', 'version')):
                    continue
                if get('outcome') == 'finished' and r['outcome'] == 'abandoned':
                    continue
                if get('outcome') not in ('', 'finished') and r['outcome'] != get('outcome'):
                    continue
                if asc is not None and r['ascension'] != asc:
                    continue
                if get('party') in ('solo', 'coop') and r['coop'] != (get('party') == 'coop'):
                    continue
                if get('exclude_abandoned') == '1' and r['abandoned']:
                    continue
                if r['floors'] < minimum:
                    continue
                day = dt.datetime.fromtimestamp(r['start']).date()
                if dates[0] and day < dates[0] or dates[1] and day > dates[1]:
                    continue
                chosen.append(r)
            return chosen

    def brief(self, r):
        return {**{k: v for k, v in r.items() if k not in ('nodes', 'deck', 'relics', 'potions', 'source')},
                'character_name': self.name(r['character']), 'cause_name': self.name(r['cause']),
                'deck_size': len(r['deck']), 'relic_count': len(r['relics']),
                'date': dt.datetime.fromtimestamp(r['start']).strftime('%d.%m.%Y %H:%M')}

    def detail(self, identifier):
        with self.lock:
            r = next((r for r in self.runs if r['id'] == identifier), None)
            if r is None:
                return None
            result = {**r, **self.brief(r)}
            result['deck'] = [{**c, 'name': self.name(model_id(c))} for c in r['deck']]
            result['relics'] = [{**c, 'name': self.name(model_id(c))} for c in r['relics']]
            result['potions'] = [{**c, 'name': self.name(model_id(c))} for c in r['potions']]
            result['nodes'] = []
            for n in r['nodes']:
                s = n['stats']
                choices = s.get('card_choices', [])
                result['nodes'].append(dict(floor=n['floor'], act=n['act'], type=n['type'],
                    room=' / '.join(self.name(x.get('model_id')) for x in n['rooms']),
                    hp=s.get('current_hp'), max_hp=s.get('max_hp'), damage=s.get('damage_taken', 0),
                    healed=s.get('hp_healed', 0), gold=s.get('current_gold'), spent=s.get('gold_spent', 0),
                    turns=n['turns'],
                    choices=[dict(name=self.name(model_id(c.get('card'))), picked=c.get('was_picked') is True) for c in choices],
                    gained=[self.name(model_id(c)) for c in s.get('cards_gained', [])],
                    removed=[self.name(model_id(c)) for c in s.get('cards_removed', [])],
                    upgraded=[self.name(model_id(c)) for c in s.get('upgraded_cards', [])],
                    potions=[self.name(model_id(c)) for c in s.get('potion_used', [])],
                    rest=s.get('rest_site_choices', []),
                    relics=[self.name(model_id(c.get('choice'))) for c in s.get('relic_choices', []) if c.get('was_picked')],
                    events=[str(c.get('title', {}).get('key', '')) for c in s.get('event_choices', [])]))
            return result

    def analysis(self, query):
        runs = self.select(query)
        count = len(runs)
        wins = sum(r['win'] for r in runs)
        def avg(values):
            values = list(values)
            return round(sum(values) / len(values), 1) if values else 0
        def groups(key):
            buckets = collections.defaultdict(list)
            for r in runs:
                buckets[str(r[key])].append(r)
            return [dict(key=k, name=self.name(k) if key == 'character' else k,
                count=len(v), wins=sum(r['win'] for r in v),
                rate=round(100 * sum(r['win'] for r in v) / len(v), 1),
                floors=avg(r['floors'] for r in v)) for k, v in sorted(buckets.items())]
        cards, relics, enemies = {}, {}, {}
        for r in runs:
            offered, picked = set(), set()
            for node in r['nodes']:
                s = node['stats']
                for c in s.get('card_choices', []):
                    cid = model_id(c.get('card'))
                    if cid:
                        offered.add(cid)
                        if c.get('was_picked'):
                            picked.add(cid)
                if node['encounter']:
                    e = enemies.setdefault(node['encounter'], dict(id=node['encounter'], name=self.name(node['encounter']), combats=0, damage=0, turns=0, deaths=0))
                    e['combats'] += 1
                    e['damage'] += number(s.get('damage_taken'))
                    e['turns'] += node['turns']
            for cid in offered:
                c = cards.setdefault(cid, dict(id=cid, name=self.name(cid), offered=0, picked=0, wins=0))
                c['offered'] += 1
                c['picked'] += cid in picked
                c['wins'] += cid in picked and r['win']
            for cid in {model_id(c) for c in r['relics']}:
                c = relics.setdefault(cid, dict(id=cid, name=self.name(cid), count=0, wins=0))
                c['count'] += 1
                c['wins'] += r['win']
            if r['outcome'] == 'loss' and r['cause'] in enemies:
                enemies[r['cause']]['deaths'] += 1
        for c in cards.values():
            c['pick_rate'] = round(100*c['picked']/c['offered'], 1)
            c['rate'] = round(100*c['wins']/c['picked'], 1) if c['picked'] else None
        for c in relics.values():
            c['rate'] = round(100*c['wins']/c['count'], 1)
        for e in enemies.values():
            e['avg_damage'] = round(e['damage']/e['combats'], 1)
            e['avg_turns'] = round(e['turns']/e['combats'], 1)
        deaths = [r for r in runs if r['outcome'] == 'loss']
        with_potions = sum(bool(r['potions']) for r in deaths)
        causes = collections.Counter(r['cause'] for r in deaths if r['cause'])
        trend = [dict(date=r['start'], floors=r['floors'], win=r['win'], character=self.name(r['character'])) for r in reversed(runs[:80])]
        insights = []
        if causes:
            cause, n = causes.most_common(1)[0]
            insights.append(f'Чаще всего поражение связано с «{self.name(cause)}»: {n} из {len(deaths)} поражений в выборке.')
        if deaths:
            insights.append(f'В {with_potions} из {len(deaths)} поражений остались зелья. Откройте эти забеги и проверьте, где их можно было использовать раньше.')
        dangerous = sorted((e for e in enemies.values() if e['combats'] >= 5), key=lambda e: e['avg_damage'], reverse=True)
        if dangerous:
            e = dangerous[0]
            insights.append(f'Самый затратный по здоровью бой среди встречавшихся ≥5 раз: «{e["name"]}», в среднем {e["avg_damage"]} урона за {e["combats"]} боёв.')
        if count >= 60:
            recent = avg(100*r['win'] for r in runs[:30]); previous = avg(100*r['win'] for r in runs[30:60])
            insights.append(f'Последние 30 забегов: {recent}% побед; предыдущие 30: {previous}%. Сравнивайте при одинаковых персонаже, сложности и версии.')
        early = sum(r['outcome'] == 'abandoned' and r['floors'] <= 3 for r in runs)
        if early:
            insights.append(f'{early} забегов помечены как прерванные на первых трёх этажах без надёжных признаков смерти. Они входят в общий процент побед; используйте фильтр результата или этажа.')
        return dict(summary=dict(count=count, wins=wins, rate=round(100*wins/count, 1) if count else 0,
            losses=len(deaths), abandoned=sum(r['outcome']=='abandoned' for r in runs),
            flagged=sum(r['abandoned'] for r in runs), hours=round(sum(r['duration'] for r in runs)/3600, 1),
            avg_floor=avg(r['floors'] for r in runs), avg_damage=avg(r['damage'] for r in runs),
            avg_deck=avg(len(r['deck']) for r in runs)),
            characters=groups('character'), ascensions=groups('ascension'), trend=trend,
            insights=insights, cards=sorted(cards.values(), key=lambda c:c['picked'], reverse=True),
            relics=sorted(relics.values(), key=lambda c:c['count'], reverse=True),
            enemies=sorted(enemies.values(), key=lambda e:e['damage'], reverse=True),
            causes=[dict(name=self.name(k), count=v) for k,v in causes.most_common()],
            runs=[self.brief(r) for r in runs])
