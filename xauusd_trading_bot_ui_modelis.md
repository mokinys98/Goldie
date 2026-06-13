# XAU/USD Trading Platform UI modelis

## 1. UI paskirtis

Frontend turi būti centrinė kelių prekybos botų valdymo platforma, kurioje
naudotojas gali:

- sukurti kelias nepriklausomas boto instancijas;
- kiekvienai instancijai priskirti brokerį, sąskaitą, strategiją ir rizikos profilį;
- keisti nustatymus per validuojamas formas;
- paleisti, pristabdyti ir sustabdyti botą;
- stebėti signalus, pavedimus, pozicijas ir riziką realiu laiku;
- vykdyti backtest, shadow, paper, demo ir live eksperimentus;
- palyginti skirtingų botų, strategijų ir konfigūracijų rezultatus;
- tirti kiekvieno sprendimo priežastis ir techninius incidentus;
- eksportuoti visus analizei reikalingus duomenis.

UI nėra tiesioginis prekybos logikos vykdytojas. Frontend siunčia komandas į
backend valdymo API, o galutinį leidimą prekiauti visada suteikia backend
risk manager.

## 2. Pagrindinis sistemos objektų modelis

```text
Workspace
├── Users and roles
├── Broker connections
├── Trading accounts
├── Bot instances
│   ├── Strategy version
│   ├── Risk profile version
│   ├── Runtime configuration version
│   ├── Current run
│   ├── Signals
│   ├── Orders
│   ├── Trades
│   ├── Positions
│   └── Incidents
├── Backtest experiments
├── Reports
└── Portfolio risk limits
```

### 2.1. Bot Template

Pakartotinai naudojamas pradinis boto nustatymų šablonas.

Pavyzdžiai:

- `XAU M5 Conservative`;
- `XAU M1 Momentum Shadow`;
- `XAU London Session Demo`;
- `XAU High Volatility Challenger`.

Šablono pakeitimas automatiškai nekeičia jau sukurtų instancijų.

### 2.2. Bot Instance

Konkreti, atskirai paleidžiama boto kopija. Ji turi:

- unikalų pavadinimą ir ID;
- instrumentą ir brokerio simbolį;
- brokerio sąskaitą;
- veikimo režimą;
- strategijos bei jos parametrų versiją;
- rizikos profilio versiją;
- prekybos sesijų ir naujienų filtrus;
- savus limitus ir būseną;
- sukūrimo, paskutinio paleidimo ir paskutinio pakeitimo informaciją.

### 2.3. Run

Vienas nekintamos konfigūracijos boto paleidimas. Pakeitus strategiją, riziką
ar svarbų runtime parametrą, dabartinis `run` uždaromas ir sukuriamas naujas.

### 2.4. Strategy Version

Versijuotas strategijos aprašas su nekintamais parametrais ir kodo versija.
UI negali perrašyti istorijoje naudotos versijos.

### 2.5. Risk Profile

Pakartotinai naudojamas ir versijuojamas rizikos taisyklių rinkinys.
Vieną profilį galima priskirti kelioms instancijoms, tačiau kiekvienas
pakeitimas sukuria naują jo versiją.

## 3. Navigacijos modelis

Pagrindinė kairioji navigacija:

1. **Command Center**
2. **Bots**
3. **Portfolio**
4. **Signals**
5. **Trades**
6. **Analytics**
7. **Backtests**
8. **Data Explorer**
9. **Incidents**
10. **Reports**
11. **Configuration**
12. **System**

Viršutinėje juostoje visada rodoma:

- aktyvus workspace;
- bendras sistemos režimas;
- gyvo ryšio indikatorius;
- aktyvių kritinių incidentų skaičius;
- UTC ir pasirinktos vietinės laiko zonos laikas;
- naudotojo rolė;
- globalus `Emergency Stop`.

## 4. Globalus Command Center

### UI-CC-001. Portfelio santrauka

Pirmame ekrane rodomos KPI kortelės:

- bendras balance ir equity;
- šiandienos, savaitės ir viso periodo neto PnL;
- atvira piniginė rizika;
- bendras drawdown;
- aktyvios pozicijos;
- šiandienos sandoriai;
- aktyvūs botai pagal režimą;
- atmesti signalai;
- kritiniai incidentai;
- duomenų ir brokerių ryšio būklė.

### UI-CC-002. Botų būsenų lentelė

Kiekvienai instancijai rodoma:

| Laukas | Reikšmė |
|---|---|
| Botas | Pavadinimas ir ID |
| Režimas | Backtest / Shadow / Paper / Demo / Live |
| Būsena | Running / Paused / Locked / Error / Offline |
| Brokeris | Brokeris ir sąskaita |
| Strategija | Pavadinimas ir versija |
| Instrumentas | XAUUSD ar brokerio simbolis |
| PnL | Dienos ir bendras |
| Atvira rizika | Suma ir procentas |
| Pozicija | Kryptis, lotas, entry, SL, TP |
| Paskutinis signalas | Tipas, laikas, sprendimas |
| Health | Ryšys, tick amžius, heartbeat |

Lentelę galima filtruoti, grupuoti, rikiuoti ir išsaugoti kaip asmeninį vaizdą.

### UI-CC-003. Bendri grafikai

Ekrane turi būti:

- equity kreivė;
- realizuoto ir nerealizuoto PnL grafikas;
- drawdown grafikas;
- atviros rizikos grafikas;
- PnL pagal botą;
- botų būsenų timeline;
- incidentų timeline.

### UI-CC-004. Globalus Emergency Stop

Paspaudus rodomas aiškus pasirinkimas:

1. tik uždrausti naujus sandorius;
2. uždrausti naujus sandorius ir uždaryti visas boto pozicijas;
3. užrakinti visą live prekybą iki rankinio atrakinimo.

Veiksmas reikalauja patvirtinimo ir priežasties.

## 5. Botų sąrašas ir kūrimo vedlys

### UI-BOT-001. Botų katalogas

Botai gali būti rodomi lentele arba kortelėmis. Palaikomi filtrai:

- būsena;
- režimas;
- brokerio sąskaita;
- strategija;
- instrumentas;
- rizikos profilis;
- pelningas / nuostolingas;
- turi incidentų;
- turi atvirą poziciją.

### UI-BOT-002. Naujo boto vedlys

Vedlio žingsniai:

1. **Identity**: pavadinimas, aprašas, žymos.
2. **Environment**: režimas ir brokerio sąskaita.
3. **Market**: instrumentas, timeframe, prekybos sesijos.
4. **Strategy**: strategija, versija ir parametrai.
5. **Risk**: rizikos profilis ir papildomi instancijos limitai.
6. **Execution**: pavedimo tipai, slippage ir timeout taisyklės.
7. **Filters**: spread, naujienos, volatilumas ir rinkos režimai.
8. **Notifications**: perspėjimų kanalai ir svarbumo lygiai.
9. **Validation**: automatiniai patikrinimai.
10. **Review**: visa konfigūracija ir sukūrimo patvirtinimas.

Vedlys turi leisti:

- pradėti nuo tuščios konfigūracijos;
- naudoti šabloną;
- klonuoti esamą botą;
- importuoti konfigūraciją;
- išsaugoti nebaigtą juodraštį.

### UI-BOT-003. Klonavimo sauga

Klonuojant botą:

- brokerio slaptažodžiai nekopijuojami į frontend;
- live režimas automatiškai pakeičiamas į `SHADOW`;
- nauja instancija pradžioje yra `STOPPED`;
- naudotojas turi iš naujo patvirtinti sąskaitą ir rizikos limitus.

### UI-BOT-004. Paleidimo patikra

Prieš `Start` UI rodo backend patikrų sąrašą:

- brokerio ryšys;
- sąskaitos tipas;
- simbolio specifikacija;
- konfigūracijos validumas;
- duomenų šviežumas;
- news šaltinis;
- minimalus lotas ir maksimali faktinė rizika;
- portfelio rizikos limitas;
- neišspręsti incidentai;
- demo/live kokybės vartai.

Nepraėjus privalomai patikrai, mygtukas `Start` neaktyvus.

## 6. Vieno boto detalus ekranas

Ekrano antraštėje rodoma:

- boto pavadinimas;
- režimo ženklelis;
- būsena;
- strategijos versija;
- brokerio sąskaita;
- paskutinio heartbeat laikas;
- `Start`, `Pause`, `Stop`, `Lock` ir `Clone` veiksmai.

Skirtukai:

1. **Overview**
2. **Live Monitor**
3. **Signals**
4. **Positions & Orders**
5. **Trades**
6. **Performance**
7. **Configuration**
8. **Run History**
9. **Logs**
10. **Incidents**

### UI-BD-001. Overview

Rodoma:

- balance, equity, free margin;
- dienos, savaitės ir run PnL;
- atvira rizika;
- drawdown;
- sandorių ir signalų skaičius;
- win rate, expectancy, profit factor;
- paskutinis sprendimas;
- aktyvūs rizikos limitai ir jų panaudojimas;
- aktyvi pozicija;
- trumpa equity kreivė;
- paskutiniai incidentai ir pakeitimai.

### UI-BD-002. Live Monitor

Realaus laiko vaizde rodoma:

- bid, ask, spread ir tick amžius;
- žvakių grafikas;
- strategijos indikatoriai;
- įėjimo, SL ir TP lygiai;
- prekybos sesijos būsena;
- news blokavimo langas;
- rinkos režimas;
- dabartinio signalo sąlygų checklist;
- risk gate patikrų būsena;
- paskutiniai pavedimo būsenų perėjimai.

### UI-BD-003. Risk cockpit

Rodomi progreso indikatoriai:

- rizika vienam sandoriui;
- dienos nuostolio panaudojimas;
- savaitės nuostolio panaudojimas;
- bendras drawdown;
- consecutive losses;
- dienos sandorių skaičius;
- atvira portfelio rizika;
- likęs limitas iki automatinio stabdymo.

Artėjant prie ribos spalva keičiasi iš neutralios į geltoną, oranžinę ir
raudoną. Spalva negali būti vienintelis būsenos indikatorius.

## 7. Konfigūracijos redaktorius

### UI-CFG-001. Formomis pagrįstas redagavimas

Pagrindinis redagavimo būdas yra tipizuotos formos, o ne laisvas YAML.
Pažengusiems naudotojams galima rodyti sugeneruotą YAML/JSON peržiūrą.

### UI-CFG-002. Konfigūracijos skyriai

- bendri boto nustatymai;
- strategijos parametrai;
- rizikos limitai;
- pozicijos dydžio taisyklės;
- prekybos sesijos;
- spread ir volatilumo filtrai;
- naujienų filtras;
- SL, TP ir išėjimo taisyklės;
- pavedimų vykdymas;
- perspėjimai;
- duomenų saugojimas.

### UI-CFG-003. Laukų metaduomenys

Kiekvienas nustatymas turi:

- aiškų pavadinimą;
- techninį raktą;
- aprašymą;
- matavimo vienetą;
- leistiną intervalą;
- numatytąją reikšmę;
- rizikos lygį;
- informaciją, ar pakeitimui reikia restart;
- informaciją, ar pakeitimas leidžiamas live režime.

### UI-CFG-004. Tarpusavio priklausomybės

UI turi dinamiškai validuoti susijusias taisykles. Pavyzdžiui:

- TP turi būti tinkamoje entry pusėje;
- SL negali būti arčiau nei brokerio `stops level`;
- maksimalus dienos nuostolis negali būti mažesnis už vieno sandorio riziką;
- news filtras negali būti privalomas be sukonfigūruoto šaltinio;
- minimalus lotas negali viršyti leidžiamos rizikos;
- live negali būti įjungtas kartu su `paper_trading: true`.

### UI-CFG-005. Pakeitimų palyginimas

Prieš išsaugant rodoma:

- sena ir nauja reikšmė;
- numatomas poveikis;
- konfliktai;
- ar bus sukurtas naujas `run`;
- ar reikės sustabdyti botą;
- rizikingų pakeitimų suvestinė.

### UI-CFG-006. Publikavimo eiga

Konfigūracija turi būsenas:

`DRAFT -> VALIDATED -> APPROVED -> ACTIVE -> SUPERSEDED`

Live instancijai galima priskirti tik patvirtintą versiją.

### UI-CFG-007. Rollback

Galima pasirinkti ankstesnę konfigūracijos versiją ir sukurti naują versiją
jos pagrindu. Istorinis įrašas nekeičiamas.

## 8. Signalų centras

### UI-SIG-001. Signalų lentelė

Laukai:

- laikas;
- botas ir run;
- instrumentas;
- timeframe;
- BUY / SELL / NO_TRADE;
- siūlomas entry, SL ir TP;
- spread;
- rinkos režimas;
- confidence ar score, jei strategija jį turi;
- galutinis sprendimas;
- priėmimo arba atmetimo priežastis;
- susijęs pavedimas ir sandoris;
- teorinis bei faktinis rezultatas.

### UI-SIG-002. Signalų filtrai

Filtravimas pagal:

- botą;
- strategijos versiją;
- režimą;
- laikotarpį;
- signalo kryptį;
- priimtas / atmestas;
- atmetimo priežastį;
- rinkos režimą;
- naujienų langą;
- spread intervalą;
- rezultatą.

### UI-SIG-003. Signalo detalė

Atidarius signalą rodoma „sprendimo kortelė“:

- kainos grafikas signalo metu;
- naudotos žvakės ir indikatoriai;
- kiekvienos strategijos sąlygos rezultatas;
- kiekvieno filtro rezultatas;
- risk manager patikros;
- konfigūracijos versija;
- sprendimo laiko seka;
- kas būtų nutikę be konkretaus filtro.

Paskutinis punktas yra analitinis modeliavimas, ne signalų perrašymas.

### UI-SIG-004. Atmestų signalų analizė

Sistema turi rodyti:

- dažniausias atmetimo priežastis;
- teoriškai laimėjusių ir pralaimėjusių atmestų signalų santykį;
- filtrų išsaugotą ir prarastą rezultatą;
- filtrų poveikį sandorių dažniui ir drawdown.

## 9. Pavedimai, pozicijos ir sandoriai

### UI-TRD-001. Atviros pozicijos

Rodoma:

- botas;
- kryptis;
- lotas;
- entry ir dabartinė kaina;
- SL ir TP;
- nerealizuotas PnL;
- atvira rizika;
- pozicijos amžius;
- maksimalus leidžiamas laikas;
- brokerio ir boto būsenos atitikimas.

### UI-TRD-002. Pavedimų timeline

Kiekvienam pavedimui rodoma visa būsenų seka nuo `PROPOSED` iki `CLOSED`,
įskaitant brokerio atsakymus, retry, partial fill ir klaidas.

### UI-TRD-003. Sandorių žurnalas

Laukai:

- planuotas ir faktinis entry;
- planuotas ir faktinis exit;
- bruto ir neto PnL;
- komisija, swap, spread ir slippage;
- R multiple;
- MAE ir MFE;
- trukmė;
- uždarymo priežastis;
- strategija ir konfigūracijos versija;
- prieš ir po sandorio buvęs equity;
- susijęs signalas ir pavedimas.

### UI-TRD-004. Rankiniai veiksmai

Leistini tik rolės suteikti veiksmai:

- pristabdyti naujus entry;
- uždaryti boto poziciją;
- perkelti botą į `LOCKED`;
- pažymėti pavedimą tyrimui.

Rankinis lotų didinimas ar SL pašalinimas per UI negalimas.

## 10. Portfolio rizikos ekranas

Keli botai gali atskirai neviršyti limitų, bet kartu sukurti per didelę
riziką. Todėl reikalingas globalus portfelio risk manager.

### UI-PORT-001. Suminė rizika

Rodoma:

- bendra atvira rizika pinigais ir procentais;
- rizika pagal brokerio sąskaitą;
- rizika pagal strategiją;
- rizika pagal instrumentą ir kryptį;
- galimas nuostolis, jei visi SL suveiktų;
- maržos panaudojimas;
- koreliuotų pozicijų koncentracija.

### UI-PORT-002. Globalūs limitai

Konfigūruojami:

- maksimalus visų botų atviras risk;
- maksimalus dienos portfelio nuostolis;
- maksimalus vienos strategijos risk;
- maksimalus vienos sąskaitos risk;
- maksimalus vienakryptis XAU/USD exposure;
- maksimalus vienu metu aktyvių live botų skaičius.

### UI-PORT-003. Konfliktai

Sistema turi aptikti:

- du botus toje pačioje sąskaitoje, atidarančius priešingas pozicijas;
- bendrą risk limito viršijimą;
- kelių botų bandymą realizuoti tą patį signalą;
- netyčinį tų pačių nustatymų dubliavimą;
- netting sąskaitoje vienas kitą keičiančius pavedimus.

## 11. Analitikos centras

### UI-AN-001. Performance dashboard

Metrikos:

- neto PnL;
- cumulative return;
- win rate;
- average win ir loss;
- expectancy;
- profit factor;
- Sharpe ir Sortino, jei imtis pakankama;
- max ir current drawdown;
- recovery factor;
- consecutive wins ir losses;
- average hold time;
- turnover;
- bendri execution kaštai;
- rezultatas R vienetais.

### UI-AN-002. Breakdown analizė

Rezultatus galima skaidyti pagal:

- botą;
- strategiją ir jos versiją;
- konfigūracijos versiją;
- režimą;
- run;
- valandą ir savaitės dieną;
- prekybos sesiją;
- BUY / SELL;
- rinkos režimą;
- volatilumo intervalą;
- spread intervalą;
- naujienų artumą;
- uždarymo priežastį;
- brokerio sąskaitą.

### UI-AN-003. Privalomi grafikai

- equity ir balance curve;
- drawdown underwater chart;
- dienos/savaitės/mėnesio PnL;
- kalendorinis heatmap;
- rezultatų pasiskirstymas;
- R multiple pasiskirstymas;
- MAE prieš MFE;
- rolling win rate;
- rolling expectancy;
- rolling profit factor;
- spread ir slippage poveikis;
- PnL pagal valandą ir sesiją;
- consecutive loss pasiskirstymas;
- signal funnel.

Signal funnel:

```text
Market observations
-> Strategy candidates
-> Valid signals
-> Risk approved
-> Orders submitted
-> Orders filled
-> Trades closed
-> Profitable trades
```

### UI-AN-004. Palyginimo režimas

Viename vaizde galima palyginti iki kelių:

- botų;
- run;
- strategijų;
- parametrų rinkinių;
- backtest/demo/live periodų.

Visiems lyginamiems objektams naudojama ta pati laiko zona ir metrikų formulė.

### UI-AN-005. Statistinis patikimumas

UI turi atskirti:

- faktinę metriką;
- imties dydį;
- pasikliautinąjį intervalą;
- perspėjimą apie per mažą imtį;
- geriausios dienos ar sandorio įtaką;
- rezultatą pašalinus geriausią ir blogiausią sandorį.

## 12. Backtest laboratorija

### UI-BT-001. Backtest kūrimo forma

Naudotojas pasirenka:

- strategiją ir versiją;
- instrumentą;
- timeframe;
- duomenų rinkinį ir periodą;
- pradinį kapitalą;
- brokerio kaštų modelį;
- spread ir slippage modelį;
- rizikos profilį;
- parametrų rinkinį;
- train, validation ir test periodus.

### UI-BT-002. Parametrų eksperimentai

Palaikoma:

- vienas backtest;
- parametrų grid;
- walk-forward;
- Monte Carlo;
- stress test;
- champion/challenger palyginimas.

UI turi rodyti numatomą skaičiavimo apimtį prieš paleidžiant eksperimentą.

### UI-BT-003. Eigos stebėjimas

Rodoma:

- būsena;
- progresas;
- pradžios laikas;
- numatomas likęs laikas;
- apdorotas periodas;
- klaidos;
- galimybė saugiai atšaukti.

### UI-BT-004. Rezultatų ekranas

Be bendrų metrikų rodomi:

- parametrų heatmap;
- walk-forward periodai;
- kaštų streso kreivė;
- Monte Carlo drawdown pasiskirstymas;
- rezultatų stabilumas gretimuose parametruose;
- mėnesių ir rinkos režimų breakdown;
- visų sandorių sąrašas;
- atkartojimo duomenys ir `run_id`.

### UI-BT-005. Promocija į shadow

Backtest konfigūraciją galima paversti nauja shadow boto instancija.
Perkeliama nekintama strategijos, rizikos ir duomenų modelio versija.

## 13. Data Explorer

### UI-DATA-001. Universalus duomenų tyrimas

Naudotojas gali pasirinkti duomenų tipą:

- ticks;
- candles;
- signals;
- rejected signals;
- orders;
- fills;
- trades;
- account snapshots;
- risk snapshots;
- news events;
- incidents;
- configuration changes;
- system logs.

### UI-DATA-002. Query builder

Filtrai kuriami formomis, be SQL rašymo:

- laiko periodas;
- botas ir run;
- instrumentas;
- lauko operatoriai;
- grupavimas;
- agregacija;
- stulpelių pasirinkimas.

### UI-DATA-003. Eksportas

Eksportuojama į:

- CSV;
- JSON;
- Parquet dideliems rinkiniams;
- sugeneruotą analizės ataskaitą.

Eksporte visada įrašoma laiko zona, filtrai, schemos versija ir generavimo laikas.

### UI-DATA-004. Duomenų kokybės ekranas

Rodomi:

- praleisti periodai;
- dubliuoti tick;
- pasenę duomenys;
- nenormalūs spread;
- kainos šuoliai;
- brokerio ir išorinio šaltinio neatitikimai;
- paskutinio sėkmingo duomenų importo laikas.

## 14. Incidentų centras

### UI-INC-001. Incidentų sąrašas

Filtrai:

- svarbumas;
- būsena;
- botas;
- komponentas;
- laikas;
- incidento tipas;
- ar paveikė poziciją;
- ar aktyvavo kill switch.

### UI-INC-002. Incidento detalė

Rodoma:

- incidento timeline;
- prieš incidentą buvusi sistemos būsena;
- susiję signalai, pavedimai ir pozicijos;
- brokerio atsakymai;
- log ištraukos;
- konfigūracijos versija;
- automatiniai sistemos veiksmai;
- operatoriaus veiksmai;
- root cause ir resolution laukai.

### UI-INC-003. Incidento eiga

`OPEN -> INVESTIGATING -> MITIGATED -> RESOLVED -> CLOSED`

Kritinis incidentas negali būti uždarytas be priežasties ir atliktų veiksmų.

### UI-INC-004. Flight recorder

Vienu veiksmu galima sugeneruoti incidento paketą su visais jo atkūrimui
reikalingais duomenimis, neįtraukiant slaptų prisijungimų.

## 15. Ataskaitos

### UI-REP-001. Standartinės ataskaitos

- dienos prekybos suvestinė;
- savaitės rizikos ataskaita;
- mėnesio strategijos rezultatų ataskaita;
- backtest ataskaita;
- demo prieš live palyginimas;
- execution quality ataskaita;
- incidentų ir uptime ataskaita;
- konfigūracijos pakeitimų auditas.

### UI-REP-002. Ataskaitų planavimas

Ataskaitą galima generuoti:

- rankiniu būdu;
- po prekybos sesijos;
- kas savaitę ar mėnesį;
- įvykus kritiniam incidentui;
- pasiekus nustatytą rezultatų ar rizikos ribą.

### UI-REP-003. Formatai

Ataskaitos rodomos UI ir eksportuojamos į PDF, CSV arba JSON.

## 16. Brokeriai, sąskaitos ir sistemos nustatymai

### UI-SYS-001. Brokerio jungtys

UI rodo:

- brokerį;
- terminalą ar API tipą;
- ryšio būseną;
- paskutinį sėkmingą ryšį;
- susietas sąskaitas;
- prieinamus simbolius;
- serverio laiko zoną;
- demo/live sąskaitos tipą.

Prisijungimo paslaptys po išsaugojimo UI neberodomos.

### UI-SYS-002. Sąskaitos detalė

- balance, equity ir margin;
- leverage;
- valiuta;
- hedging/netting tipas;
- aktyvios boto instancijos;
- sąskaitos lygio limitai;
- pozicijos ir pavedimai;
- brokerio specifikacijų istorija.

### UI-SYS-003. Strategijų registras

Rodomos strategijos, jų versijos, palaikomi parametrai, kodo versija,
naudojančios instancijos ir kokybės vartų būsena.

### UI-SYS-004. Rizikos profilių registras

Galima kurti, klonuoti, versijuoti ir archyvuoti rizikos profilius.
Naudojamas profilis negali būti ištrintas.

## 17. Prieigos kontrolė

Rolės:

### Viewer

Gali matyti dashboard, signalus, sandorius, analitiką ir ataskaitas.

### Analyst

Papildomai gali kurti backtest, palyginimus ir eksportuoti duomenis.

### Operator

Papildomai gali paleisti ir stabdyti shadow, paper bei demo botus, valdyti
incidentus ir uždaryti boto poziciją.

### Risk Manager

Gali tvirtinti rizikos profilius, limitų pakeitimus ir live kokybės vartus.

### Administrator

Valdo naudotojus, brokerių jungtis, sistemos nustatymus ir live leidimus.

### UI-AUTH-001. Dvigubas patvirtinimas

Šiems veiksmams rekomenduojamas dviejų skirtingų rolių patvirtinimas:

- pirmas live režimo įjungimas;
- portfelio rizikos limito didinimas;
- live kill switch atrakinimas po kritinio incidento;
- naujos strategijos versijos aktyvavimas live bote.

## 18. Realaus laiko ir UX reikalavimai

### UI-UX-001. Duomenų šviežumas

Kiekviena realaus laiko kortelė turi rodyti paskutinio atnaujinimo laiką.
Praradus WebSocket/SSE ryšį, UI aiškiai pažymimas kaip `STALE`.

### UI-UX-002. Optimistinių komandų draudimas

UI negali parodyti boto kaip paleisto, sustabdyto ar užrakinto, kol backend
nepatvirtino faktinės būsenos.

### UI-UX-003. Pavojingi veiksmai

Live režimo veiksmai:

- vizualiai atskirti nuo demo;
- reikalauti aiškaus patvirtinimo;
- rodyti paveikiamą sąskaitą, botą ir atviras pozicijas;
- reikalauti priežasties;
- turėti audit įrašą.

### UI-UX-004. Desktop-first

Pilnas valdymas projektuojamas desktop ekranui. Mobiliajame režime leidžiama:

- stebėti būseną;
- gauti perspėjimus;
- aktyvuoti emergency stop;
- peržiūrėti incidentus.

Sudėtingas konfigūravimas ir live paleidimas mobiliajame režime išjungiamas.

### UI-UX-005. Vizualinė semantika

- `SHADOW`: violetinė ar neutrali;
- `PAPER`: mėlyna;
- `DEMO`: žydra;
- `LIVE`: aiškiai raudona arba oranžinė;
- `LOCKED`: tamsiai raudona;
- `PAUSED`: geltona;
- `RUNNING`: žalia.

Spalvos visada papildomos tekstu ir ikona.

### UI-UX-006. Lentelių galimybės

Didelės duomenų lentelės turi:

- server-side pagination;
- stulpelių pasirinkimą;
- filtrus;
- rikiavimą;
- prisegtus stulpelius;
- išsaugomus vaizdus;
- eksportą;
- nuorodą į konkretų filtruotą vaizdą.

## 19. UI ir backend API ribos

Frontend neturi:

- saugoti brokerio slaptažodžių naršyklėje;
- skaičiuoti galutinio leidžiamo loto;
- apeiti risk manager;
- tiesiogiai komunikuoti su rinkos duomenų ar vykdymo tiekėju;
- pats nuspręsti, kad pavedimas įvykdytas;
- redaguoti istorinių run duomenų;
- lokaliai įjungti live režimo.

Backend turi pateikti:

- REST arba GraphQL valdymo API;
- WebSocket arba SSE realaus laiko įvykiams;
- tipizuotas konfigūracijos schemas;
- visų komandų `command_id`;
- komandų būsenas ir audit trail;
- eksportų ir ilgų backtest užduočių asinchroninį vykdymą.

## 20. Siūloma frontend techninė architektūra

Galimas pradinis pasirinkimas:

- React su TypeScript;
- Next.js arba Vite;
- TanStack Query serverio būsenai;
- WebSocket/SSE realaus laiko srautui;
- React Hook Form ir schema pagrįsta validacija;
- TanStack Table didelėms lentelėms;
- TradingView Lightweight Charts arba analogas kainos grafikams;
- ECharts arba Plotly analitikai;
- centralizuotas design system;
- OpenAPI generuojami API tipai.

Svarbu atskirti:

- serverio būseną;
- formos juodraštį;
- patvirtintą aktyvią konfigūraciją;
- realaus laiko prekybos įvykius;
- ilgai vykdomų užduočių būseną.

## 21. UI MVP

### P0

- prisijungimas ir rolės;
- botų sąrašas;
- naujo boto kūrimas ir klonavimas;
- boto Overview bei Live Monitor;
- tipizuotas konfigūracijos redaktorius;
- Start, Pause, Stop ir Lock komandos;
- signalų lentelė ir signalo detalė;
- pozicijos, pavedimai ir sandorių žurnalas;
- risk cockpit;
- incidentų sąrašas;
- globalus Emergency Stop;
- realaus laiko ryšio ir pasenusių duomenų indikacija.

### P1

- globalus Command Center;
- portfolio rizikos ekranas;
- performance analytics;
- backtest laboratorija;
- run ir konfigūracijos versijų palyginimas;
- ataskaitos;
- perspėjimai;
- duomenų eksportas.

### P2

- Data Explorer;
- parametrų heatmap ir Monte Carlo vizualizacijos;
- champion/challenger valdymas;
- pažangus incidentų flight recorder;
- išsaugomi dashboard vaizdai;
- automatinės degradacijos perspėjimai.

## 22. Pagrindiniai UI acceptance criteria

- Vienoje sistemoje galima sukurti bent dvi boto instancijas su skirtingomis
  strategijomis ir rizikos profiliais.
- Vienos instancijos pakeitimai nepaveikia kitos instancijos.
- Negalima aktyvuoti live boto nepraėjus backend kokybės ir rizikos vartams.
- Kiekvienas UI valdymo veiksmas turi autorių, laiką, priežastį ir rezultatą.
- Galima nuo sandorio nueiti iki pavedimo, signalo, run ir konfigūracijos.
- Galima matyti, kodėl signalas buvo atmestas.
- Galima palyginti dviejų botų arba run rezultatus vienodame periode.
- UI aiškiai atskiria demo ir live duomenis.
- Dingus realaus laiko ryšiui, UI nerodo pasenusių duomenų kaip aktualių.
- Globalus kill switch veikia nepriklausomai nuo pasirinkto boto ekrano.
- Portfelio limitas gali atmesti sandorį net jei konkretaus boto limitas
  neviršytas.
- Istorinių konfigūracijų ir run negalima tyliai perrašyti.

## 23. Rekomenduojami pirmieji dizaino maketai

Pirmu etapu verta suprojektuoti šiuos septynis ekranus:

1. Globalus Command Center.
2. Botų sąrašas.
3. Naujo boto kūrimo vedlys.
4. Boto Live Monitor su risk cockpit.
5. Konfigūracijos redaktorius ir pakeitimų palyginimas.
6. Signalų centras su sprendimo kortele.
7. Analitikos ekranas su botų ir run palyginimu.

Šie ekranai patikrins svarbiausią produkto modelį: ar naudotojas geba saugiai
sukurti kelias instancijas, suprasti jų sprendimus, kontroliuoti riziką ir
palyginti realius rezultatus.

## 24. Technologinis įgyvendinimas

Detalus frontend, backend, prekybos branduolio, duomenų bazės, OANDA collector,
hostingo ir CI/CD technologijų pasirinkimas aprašytas dokumente
`xauusd_trading_bot_technologiju_architektura.md`.
