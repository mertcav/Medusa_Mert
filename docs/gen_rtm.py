import re, collections

brd=open('docs/BRD.md').read()
srs=open('docs/SRS.md').read()
wbs=open('docs/todo_list.md').read()

# ---- FR master ----
fr_order=[]; seen=set()
for m in re.findall(r'FR-[A-Z]+-\d+', brd):
    if m not in seen: seen.add(m); fr_order.append(m)
area_order=[]
for fr in fr_order:
    a=fr.rsplit('-',1)[0]
    if a not in area_order: area_order.append(a)
area_name={
 'FR-TEN':'Tenant & Organizasyon','FR-IAM':'IAM, RBAC & Break-glass','FR-AGT':'Agent Yaşam Döngüsü',
 'FR-TEL':'Telefoni & Çağrı Yönetimi','FR-RTC':'Gerçek Zamanlı Konuşma Motoru','FR-STT':'STT','FR-TTS':'TTS',
 'FR-LLM':'LLM Orkestrasyonu','FR-KB':'Bilgi Tabanı & RAG','FR-TOOL':'Tool & Entegrasyon',
 'FR-AUTH':'Çağrı-içi Kimlik Doğrulama','FR-HND':'İnsan Temsilciye Aktarım','FR-OUT':'Outbound & Kampanya & Consent',
 'FR-REC':'Kayıt, Transkript & PII','FR-ANA':'Analitik & Kalite','FR-TST':'Test & Simülasyon',
 'FR-BIL':'Faturalama & Kullanım','FR-RES':'Kaynak Verimliliği'}
wbs_sec={'FR-TEN':'1, 12.4','FR-IAM':'12','FR-AGT':'3.2, 13.4, 20','FR-TEL':'2.1, 9, 10.2',
 'FR-RTC':'2.2, 3','FR-STT':'2.2, 4.2/4.3','FR-TTS':'2.2, 4.2/4.3','FR-LLM':'3.3, 5',
 'FR-KB':'6','FR-TOOL':'7','FR-AUTH':'8','FR-HND':'9','FR-OUT':'10','FR-REC':'1.2, 11',
 'FR-ANA':'14','FR-TST':'18','FR-BIL':'15','FR-RES':'3.1, 5, 16'}

# ---- SR rows ----
sr_rows=[]
for line in srs.splitlines():
    m=re.match(r'\|\s*(SR-[A-Z]+-\d+)\s*\|.*?\|\s*([^|]*?)\s*\|\s*([TDAI])\s*\|', line)
    if m:
        sr_rows.append((m.group(1),re.findall(r'FR-[A-Z]+-\d+',m.group(2)),
                        re.findall(r'NFR\s*10\.\d',m.group(2)),m.group(3)))
fr2sr=collections.defaultdict(list); sr_method={}
nfr_groups=collections.OrderedDict()
for sid,frs,nfrs,meth in sr_rows:
    sr_method[sid]=meth
    for fr in frs: fr2sr[fr].append(sid)
    for n in nfrs: nfr_groups.setdefault(n,[]).append((sid,meth))
def tc(s): return 'TC-'+s[3:]

# ---- WBS -> FR / NFR ----
def expand(token):
    m=re.match(r'(FR-[A-Z]+-)(\d+(?:/\d+)*)',token); base=m.group(1)
    return [base+n.zfill(3) for n in m.group(2).split('/')]
fr2wbs=collections.defaultdict(list); nfr2wbs=collections.defaultdict(list)
for line in wbs.splitlines():
    mm=re.search(r'\*\*([0-9]+(?:\.[0-9]+)+)\*\*',line)
    if not mm: continue
    wid=mm.group(1)
    frs=[]
    for t in re.findall(r'FR-[A-Z]+-\d+(?:/\d+)*',line): frs+=expand(t)
    for fr in frs:
        if wid not in fr2wbs[fr]: fr2wbs[fr].append(wid)
    for n in re.findall(r'NFR\s*10\.\d',line):
        if wid not in nfr2wbs[n]: nfr2wbs[n].append(wid)

# ---- implicit (no direct WBS) recommended homes ----
implicit={
 'FR-IAM-004':('12.1.1, 12.1.2','RBAC + permission-key kataloğu ayrımı; ayrı görev gerekmez'),
 'FR-AGT-007':('13.4.4, 20.1','Agent Builder kapsam/numara/saat alanları + yaşam döngüsü'),
 'FR-TEL-003':('— (YENİ GÖREV)','CC (Avaya/Genesys/Cisco/Amazon Connect) entegrasyonu için ayrı WBS görevi YOK → eklenmeli (öner: 2.1.10, F2)'),
 'FR-RTC-007':('3.1.3, 2.2.3','Turn-taking + endpointing içinde backchannel yorumu'),
 'FR-STT-003':('4.2.1','STT adapter dil/lehçe konfigürasyonu'),
 'FR-STT-007':('3.3.6, 4.2.1','Düşük confidence → kontrollü teyit turu'),
 'FR-TTS-003':('4.2.3, 13.4.7','TTS adapter + Voice/Model ayarları'),
 'FR-TTS-010':('16.1','TTS cache (16.1 yalnız FR-RES-003 atıfı veriyor; FR-TTS-010 atıfı eklenmeli)'),
 'FR-REC-008':('13.4.11, 13.4.12, 11.6','Kayıt/transkript ekranları + erişim audit'),
 'FR-ANA-005':('14.2.2, 14.1.2','Konuşma süresi metriği analitik kapsamında'),
 'FR-ANA-006':('14.1.2','STT/LLM/TTS gecikme bileşenleri teknik metriklerde'),
 'FR-RES-002':('2.2.1, 3.1.1','Streaming pipeline (SR-RTC-001 üzerinden full-buffering yok)'),
}

mtype={'T':'Test','D':'Demo','A':'Analiz','I':'İnceleme'}
out=[]
def w(s=''): out.append(s)

# ===== forward FR matrix =====
w("<!-- BEGIN-AUTOGEN: bu bölüm docs/BRD.md+SRS.md+todo_list.md'ten türetilir -->")
for area in area_order:
    w(f"\n#### {area}-* — {area_name[area]}\n")
    w("| FR-ID | SR-ID(ler) | Test Case (yöntem) | WBS Görev(leri) |")
    w("|-------|------------|--------------------|-----------------|")
    for fr in [f for f in fr_order if f.rsplit('-',1)[0]==area]:
        srs_l=fr2sr.get(fr,[])
        srtxt=', '.join(srs_l) if srs_l else '—'
        tctxt=', '.join(f"{tc(s)} ({sr_method[s]})" for s in srs_l) if srs_l else '—'
        if fr2wbs.get(fr): wtxt=', '.join(fr2wbs[fr])
        elif fr in implicit: wtxt=implicit[fr][0]+' *(örtük)*'
        else: wtxt='—'
        w(f"| {fr} | {srtxt} | {tctxt} | {wtxt} |")
w("\n<!-- END-AUTOGEN forward FR -->")
open('/tmp/sec_fr.md','w').write('\n'.join(out))

# ===== NFR matrix =====
out=[]
nfr_name={'NFR 10.1':'Performans & Gecikme','NFR 10.2':'Kaynak Verimliliği / Density',
 'NFR 10.3':'Ölçeklenebilirlik','NFR 10.4':'Kullanılabilirlik','NFR 10.5':'Felaket Kurtarma',
 'NFR 10.6':'Güvenlik','NFR 10.7':'Veri Yerleşimi / Residency'}
for nfr,items in nfr_groups.items():
    wlist=', '.join(nfr2wbs.get(nfr,[])) or '—'
    w(f"\n#### {nfr} — {nfr_name[nfr]}")
    w(f"\n**İlgili WBS görevleri:** {wlist}\n")
    w("| NFR | SR-ID | Test Case (yöntem) |")
    w("|-----|-------|--------------------|")
    for sid,meth in items:
        w(f"| {nfr} | {sid} | {tc(sid)} ({meth}) |")
open('/tmp/sec_nfr.md','w').write('\n'.join(out))

# ===== implicit gap table =====
out=[]
w("| FR-ID | SR-ID | Önerilen / kapsayan WBS | Not |")
w("|-------|-------|--------------------------|-----|")
for fr in fr_order:
    if fr in implicit:
        srs_l=', '.join(fr2sr.get(fr,[]))
        home,note=implicit[fr]
        w(f"| {fr} | {srs_l} | {home} | {note} |")
open('/tmp/sec_gap.md','w').write('\n'.join(out))

# ===== acceptance gate (BRD §19) -> SR -> TC -> WBS =====
gate=[
 (1,"≥2 STT",["SR-STT-001"]),(2,"≥2 TTS",["SR-TTS-001"]),(3,"≥2 LLM",["SR-LLM-001"]),
 (4,"Birincil kesintide fallback",["SR-STT-008","SR-TTS-008","SR-LLM-010"]),
 (5,"Inbound+outbound tamamlanır",["SR-TEL-001"]),
 (6,"Warm+cold transfer",["SR-TEL-007","SR-HND-004"]),
 (7,"CRM oku + kontrollü işlem",["SR-TOOL-001","SR-TOOL-006"]),
 (8,"Prompt injection sızıntı yok",["SR-LLM-007"]),
 (9,"Tenant izolasyonu",["SR-TEN-002"]),(10,"P95 gecikme",["SR-PERF-002"]),
 (11,"Tasarım kapasitesinde yük testi",["SR-TST-006","SR-SCAL-001"]),
 (12,"Retention uygulanır",["SR-REC-006","SR-REC-010"]),
 (13,"PII redaction",["SR-REC-004","SR-REC-005"]),
 (14,"Outbound consent/opt-out",["SR-OUT-003","SR-OUT-006","SR-TEL-014"]),
 (15,"Agent rollback",["SR-AGT-006"]),
 (16,"Kritik işlemler audit'te",["SR-IAM-006","SR-TOOL-010"]),
 (17,"DR senaryosu",["SR-DR-002"]),
 (18,"Temsilciye özet/bağlam",["SR-HND-004","SR-HND-005"]),
 (19,"Regression production öncesi",["SR-TST-004","SR-TST-005"]),
 (20,"Pentest kritik bulgu yok",["SR-SEC-009"]),
 (21,"Yük altında per-call kaynak bütçede",["SR-DEN-001","SR-TST-009"]),
 (22,"Worker başına density hedefi",["SR-DEN-002"]),
]
out=[]
w("| BRD §19 | Kriter (özet) | SR(ler) | Test Case(ler) | WBS (Ek A) |")
w("|---------|---------------|---------|----------------|------------|")
for n,desc,srs_l in gate:
    tcs=', '.join(tc(s) for s in srs_l)
    wset=[]
    for s in srs_l:
        for fr in [sid_fr for sid,frs,nfrs,meth in sr_rows if sid==s for sid_fr in frs]:
            for wid in fr2wbs.get(fr,[]):
                if wid not in wset: wset.append(wid)
    wtxt=', '.join(wset) if wset else '§0.3 / §18 / §19'
    w(f"| {n} | {desc} | {', '.join(srs_l)} | {tcs} | {wtxt} |")
open('/tmp/sec_gate.md','w').write('\n'.join(out))

# ===== stats =====
fr_direct=len([f for f in fr_order if fr2wbs.get(f)])
print("STATS")
print("FR:",len(fr_order),"SR:",len(sr_rows),"TC(=SR):",len(sr_rows))
print("WBS tasks w/ FR ref:",len(set(w for f in fr2wbs for w in fr2wbs[f])))
print("FR direct WBS:",fr_direct,"FR implicit:",len(implicit),"FR orphan SR:",len([f for f in fr_order if f not in fr2sr]))
