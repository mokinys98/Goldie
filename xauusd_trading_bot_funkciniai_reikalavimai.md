# XAU/USD Trading Bot funkciniai reikalavimai

## 1. Produkto vizija

Produktas turi būti kuriamas kaip kontroliuojama algoritminės prekybos
eksperimentų platforma, o ne vien signalą generuojantis skriptas.

Sistema turi:

- vienodai vykdyti strategiją istoriniuose duomenyse, paper, demo ir live režimuose;
- prieš kiekvieną veiksmą tikrinti rizikos taisykles;
- paaiškinti, kodėl signalas priimtas, atmestas ar sandoris uždarytas;
- atkurti savo būseną po proceso, terminalo ar ryšio sutrikimo;
- leisti įrodyti, kad rezultatas nėra backtest optimizavimo ar vieno gero periodo pasekmė;
- pagal nutylėjimą neprekiauti, jeigu trūksta duomenų arba sistema nėra tikra dėl savo būsenos.

Pagrindinis produkto principas:

> Abejonės atveju neatidaryti sandorio. Kapitalo apsauga yra aukštesnio
> prioriteto už signalo realizavimą.

## 2. Naudotojai ir rolės

### FR-USER-001. Sistemos savininkas

Savininkas gali keisti strategijos ir rizikos konfigūraciją, paleisti testus,
peržiūrėti rezultatus ir patvirtinti perėjimą į kitą veikimo režimą.

### FR-USER-002. Tik skaitymo režimas

Stebėtojas gali matyti būseną, sandorius, metrikas ir incidentus, bet negali
keisti parametrų ar įjungti live prekybos.

### FR-USER-003. Avarinis operatorius

Operatorius gali nedelsiant:

- sustabdyti naujų sandorių atidarymą;
- pasirinktinai uždaryti visas boto pozicijas;
- atjungti live prekybos leidimą;
- pažymėti incidento pradžią ir priežastį.

## 3. Veikimo režimai

### FR-MODE-001. Režimų izoliacija

Sistema privalo turėti atskirus režimus:

1. `BACKTEST`
2. `REPLAY`
3. `SHADOW`
4. `PAPER`
5. `DEMO`
6. `LIVE`

Tas pats strategijos ir rizikos kodas turi būti naudojamas visuose režimuose.
Keistis gali tik rinkos duomenų šaltinis ir pavedimų vykdymo adapteris.

### FR-MODE-002. Shadow režimas

Shadow režime sistema gauna gyvus rinkos duomenis, priima pilną prekybos
sprendimą ir registruoja virtualų pavedimą, tačiau nieko nesiunčia brokeriui.

### FR-MODE-003. Live režimo apsauga

Live režimas gali būti įjungtas tik kai:

- konfigūracijoje aiškiai nustatytas `allow_live_trading: true`;
- pateiktas papildomas vienkartinis operatoriaus patvirtinimas;
- brokerio sąskaitos tipas patikrintas ir sutampa su konfigūracija;
- praėti demo režimo kokybės vartai;
- nėra aktyvaus kill switch ar neišspręsto kritinio incidento.

### FR-MODE-004. Sausas pavedimo patikrinimas

Prieš įjungiant demo ar live režimą sistema turi gebėti patikrinti simbolio
specifikaciją ir paskaičiuoti hipotetinį pavedimą jo neišsiųsdama.

## 4. Konfigūracija ir eksperimentų valdymas

### FR-CFG-001. Konfigūracijos validavimas

Paleidimo metu sistema privalo validuoti visus parametrus pagal schemą.
Trūkstamas, nežinomas ar nelogiškas parametras turi stabdyti prekybos modulį.

### FR-CFG-002. Nekintama eksperimento versija

Kiekvienam backtest ar prekybos paleidimui turi būti sukurtas `run_id`, prie
kurio saugoma:

- strategijos versija;
- konfigūracijos kopija ir kontrolinė suma;
- programos Git commit;
- duomenų rinkinio versija;
- brokerio ir sąskaitos identifikatorius;
- paleidimo ir sustabdymo laikas;
- veikimo režimas.

### FR-CFG-003. Parametrų pakeitimų auditas

Kiekvienas pakeitimas turi turėti seną reikšmę, naują reikšmę, laiką,
autorių ir pakeitimo priežastį.

### FR-CFG-004. Draudžiami nustatymai

Sistema turi atmesti konfigūraciją, kuri leidžia:

- martingale;
- pozicijos didinimą po nuostolio;
- poziciją be stop-loss;
- neapribotą dienos ar bendrą drawdown;
- daugiau live pozicijų nei leidžia rizikos politika.

### FR-CFG-005. Parametrų užšaldymas

Prasidėjus forward testui, strategijos parametrai užšaldomi pasirinktam
vertinimo periodui. Pakeitimas pradeda naują eksperimentą ir naują `run_id`.

## 5. Brokerio ir rinkos duomenų integracija

### FR-BRK-001. Brokerio adapteris

Brokerio funkcijos turi būti pasiekiamos per bendrą sąsają:

- prisijungti ir patikrinti ryšį;
- gauti sąskaitos būseną;
- gauti simbolio specifikaciją;
- gauti tick ir OHLCV duomenis;
- pateikti, keisti ir atšaukti pavedimą;
- gauti atviras pozicijas ir pavedimų istoriją;
- uždaryti poziciją;
- patikrinti prekybos sesijos būseną.

### FR-BRK-002. Simbolio specifikacija

Sistema negali remtis hardcoded XAU/USD punktų verte. Ji turi iš brokerio
gauti bent:

- tikrą simbolio kodą;
- skaitmenų ir tick dydį;
- tick vertę sąskaitos valiuta;
- kontrakto dydį;
- minimalų, maksimalų ir žingsninį lotą;
- stop ir freeze lygius;
- komisinius, jei jie pasiekiami;
- prekybos sesijų laiką.

### FR-BRK-003. Sąskaitos suderinamumas

Prieš pavedimą tikrinama sąskaitos valiuta, leverage, margin režimas,
hedging/netting režimas ir laisva marža.

### FR-DATA-001. Duomenų kokybė

Kiekvienas tick ar žvakė turi būti tikrinami dėl:

- pasenusio timestamp;
- dubliavimo;
- praleistos sekos;
- neigiamos arba nulinės kainos;
- `ask < bid`;
- nenormalaus kainos šuolio;
- nebaigtos žvakės panaudojimo užbaigtos žvakės vietoje.

### FR-DATA-002. Laiko normalizavimas

Viduje visi laikai saugomi UTC. Vartotojo, brokerio ir naujienų laiko zonos
konvertuojamos aiškiai, įskaitant vasaros laiko pasikeitimus.

### FR-DATA-003. Duomenų spragos

Esant nepaaiškintai duomenų spragai ar pasenusiam kainos srautui, nauji
sandoriai blokuojami, o incidentas registruojamas.

## 6. Strategijos variklis

### FR-STR-001. Deterministinis rezultatas

Ta pati strategijos versija su tais pačiais įvesties duomenimis ir
parametrais turi sugeneruoti identišką sprendimą.

### FR-STR-002. Signalo paaiškinimas

Kiekvienas sprendimas turi pateikti:

- `BUY`, `SELL` arba `NO_TRADE`;
- panaudotų indikatorių reikšmes;
- įėjimo sąlygų rezultatą;
- filtrų rezultatą;
- siūlomą entry, SL, TP ir galiojimo laiką;
- žmogui suprantamą priežasties kodą.

### FR-STR-003. Tik užbaigtos žvakės

Pagal nutylėjimą signalai skaičiuojami iš užbaigtų žvakių. Jei naudojama
einamoji žvakė ar tick duomenys, tai turi būti aiškiai nurodyta strategijoje.

### FR-STR-004. Signalo galiojimas

Signalas turi `expires_at`. Pasibaigus galiojimui jo negalima realizuoti.

### FR-STR-005. Rinkos režimo filtras

Strategija gali klasifikuoti rinką bent į:

- trend;
- range;
- aukšto volatilumo;
- žemo likvidumo;
- naujienų ar nenormalaus judėjimo režimą.

Kiekviena strategija deklaruoja, kuriuose režimuose jai leidžiama veikti.

### FR-STR-006. Strategijų registras

Sistema turi leisti pridėti naują strategiją nekeičiant brokerio, rizikos,
vykdymo ir ataskaitų modulių.

## 7. Prekybos leidimo vartai

### FR-GATE-001. Privalomi patikrinimai

Prieš kiekvieną pavedimą sistema ta pačia tvarka patikrina:

1. veikimo režimą ir live leidimą;
2. ryšio bei duomenų šviežumą;
3. prekybos sesiją;
4. naujienų blokavimo langą;
5. spread ir volatilumo ribas;
6. atviras pozicijas bei laukiančius pavedimus;
7. dienos, savaitės ir bendro drawdown limitus;
8. sandorių skaičių ir consecutive loss limitą;
9. signalo galiojimą;
10. lotą, SL, TP, maržą ir brokerio apribojimus.

Vienam patikrinimui nepraėjus, pavedimas nesiunčiamas.

### FR-GATE-002. News fail-closed taisyklė

Jei naujienų filtras privalomas, bet jo duomenys nepasiekiami ar pasenę,
sistema neprekiauja. Rankinis apėjimas galimas tik su audituojama priežastimi.

### FR-GATE-003. Dinaminis spread filtras

Be absoliučios spread ribos turi būti palaikoma santykinė riba, pavyzdžiui:

- spread kaip planuojamo SL dalis;
- spread kaip numatomo pelno dalis;
- spread nuokrypis nuo tos sesijos medianos.

### FR-GATE-004. Mažiausio loto veto

Jei brokerio minimalus lotas rizikuotų daugiau nei leidžia politika, sistema
privalo praleisti sandorį. Ji negali apvalinti loto aukštyn rizikos sąskaita.

## 8. Rizikos valdymas

### FR-RISK-001. Pozicijos dydis

Pozicijos dydis skaičiuojamas iš:

- dabartinio equity;
- leidžiamos rizikos procento;
- realaus atstumo iki SL;
- simbolio tick dydžio ir tick vertės;
- komisinių ir konservatyvaus slippage rezervo;
- brokerio loto žingsnio.

### FR-RISK-002. Rizikos šaltinis

Rizikos limitai skaičiuojami nuo mažesnės reikšmės tarp balance ir equity,
nebent patvirtinta rizikos politika nurodo dar konservatyvesnę bazę.

### FR-RISK-003. Keli limitų sluoksniai

Sistema turi palaikyti:

- riziką vienam sandoriui;
- maksimalų atvirą piniginį risk;
- dienos realizuotą ir bendrą PnL limitą;
- savaitės nuostolio limitą;
- bendrą equity drawdown limitą;
- consecutive loss limitą;
- sandorių skaičiaus limitą;
- cooldown laiką po nuostolio ar incidento.

### FR-RISK-004. Limitų reset taisyklės

Dienos ir savaitės ribų pradžia turi būti apibrėžta UTC arba brokerio laiku.
Proceso perkrovimas negali nuresetinti limitų.

### FR-RISK-005. Kill switch

Kill switch turi turėti bent tris lygius:

- `PAUSE_ENTRIES`: draudžia naujus sandorius, esamus valdo toliau;
- `CLOSE_AND_PAUSE`: bando kontroliuojamai uždaryti boto pozicijas;
- `LOCKED`: prekyba išjungta iki rankinio incidento uždarymo.

### FR-RISK-006. Nepriklausomas rizikos veto

Strategija gali tik siūlyti sandorį. Galutinį leidimą suteikia atskiras risk
manager, kurio strategija negali apeiti.

## 9. Pavedimų vykdymas

### FR-EXEC-001. Pavedimo būsenų mašina

Pavedimas turi aiškias būsenas, pavyzdžiui:

`PROPOSED -> VALIDATED -> SUBMITTED -> ACKNOWLEDGED -> FILLED -> PROTECTED
-> CLOSING -> CLOSED`

Klaidos ir dalinis įvykdymas turi atskiras būsenas.

### FR-EXEC-002. Idempotency

Kiekvienas pavedimas turi unikalų `client_order_id`. Pakartotinis procesas po
timeout ar perkrovimo negali netyčia sukurti antros pozicijos.

### FR-EXEC-003. SL apsauga

Sandoris laikomas sėkmingai atidarytu tik kai patvirtinta jo pozicija ir
apsauginis SL. Jei SL nepavyksta uždėti:

1. nauji pavedimai blokuojami;
2. poziciją bandoma nedelsiant uždaryti;
3. aktyvuojamas kritinis incidentas.

### FR-EXEC-004. Leidžiamas slippage

Pavedimas atmetamas arba atšaukiamas, jei kaina pablogėjo daugiau nei leidžia
strategija ir brokerio pavedimo tipas.

### FR-EXEC-005. Dalinis įvykdymas

Sistema turi mokėti aptikti dalinį fill, perskaičiuoti faktinę riziką ir
apsaugoti tik realiai atidarytą kiekį.

### FR-EXEC-006. Pozicijų nuosavybė

Botas valdo tik savo `magic number` ar kitu patikimu identifikatoriumi
pažymėtas pozicijas. Rankinių sandorių jis nekeičia.

### FR-EXEC-007. Perkrovimo atkūrimas

Paleidimo metu sistema sulygina vietinę būseną su brokeriu. Neatitikimas
stabdo naujus sandorius iki reconciliacijos.

## 10. Sandorio gyvavimo ciklas

### FR-TRADE-001. Uždarymo priežastys

Pozicija gali būti uždaryta dėl:

- stop-loss;
- take-profit;
- maksimalaus laiko;
- strategijos invalidacijos;
- trailing ar break-even taisyklės;
- sesijos pabaigos;
- rizikos kill switch;
- operatoriaus komandos;
- techninio incidento.

### FR-TRADE-002. Prioritetai

Rizikos ir avarinio uždarymo taisyklės turi aukštesnį prioritetą už
strategijos išėjimo signalą.

### FR-TRADE-003. Faktinis rezultatas

Po uždarymo saugoma planuota ir faktinė:

- entry ir exit kaina;
- pozicijos apimtis;
- SL ir TP;
- komisija, swap ir slippage;
- bruto bei neto PnL;
- R multiple;
- sandorio trukmė;
- uždarymo priežastis.

## 11. Backtest ir tyrimų laboratorija

### FR-BT-001. Be look-ahead bias

Strategija kiekviename laiko taške gali naudoti tik tuo metu buvusius
duomenis. Testai turi aptikti dažniausias ateities duomenų panaudojimo klaidas.

### FR-BT-002. Realistiškas vykdymas

Backtest turi modeliuoti:

- bid/ask kainas;
- kintantį spread;
- komisinius;
- slippage;
- dalinį ar atmestą pavedimą, jei pasirinktas modelis tai palaiko;
- SL/TP įvykdymo tvarką toje pačioje žvakėje;
- sesijų ir naujienų filtrus.

Jei M1 žvakėje vienu metu galėjo būti pasiektas ir SL, ir TP, rezultatas
negali automatiškai būti parinktas boto naudai.

### FR-BT-003. Train, validation ir test periodai

Duomenys turi būti dalijami chronologiškai. Galutinis test periodas negali
būti naudojamas parametrų parinkimui.

### FR-BT-004. Walk-forward analizė

Sistema turi palaikyti slenkančius optimizavimo ir patikros langus, kad būtų
matoma strategijos elgsena skirtinguose rinkos režimuose.

### FR-BT-005. Robustumo testai

Ataskaita turi parodyti:

- gretimų parametrų rezultatų stabilumą;
- spread ir slippage streso scenarijus;
- Monte Carlo sandorių sekos permaišymą;
- rezultatą pagal mėnesį, sesiją, kryptį ir rinkos režimą;
- geriausios dienos ar sandorio įtaką bendram rezultatui.

### FR-BT-006. Lyginamasis benchmark

Strategija turi būti lyginama bent su:

- `NO_TRADE`;
- paprastu atsitiktiniu signalu su tomis pačiomis rizikos taisyklėmis;
- paprasta nekoreguota strategijos versija.

### FR-BT-007. Pakankamos imties taisyklė

100–200 signalų galima naudoti techniniam MVP patikrinimui, bet ne tvirtai
išvadai apie matematinį pranašumą. Kokybės vartuose turi būti vertinamas
pasikliautinasis intervalas, o ne vien fiksuotas sandorių skaičius.

## 12. Žurnalai, atsekamumas ir duomenų modelis

### FR-LOG-001. Įvykių žurnalas

Kiekvienas svarbus įvykis saugomas struktūrizuotai su:

- UTC timestamp;
- `run_id`;
- `signal_id`;
- `client_order_id`;
- `broker_order_id`;
- įvykio tipu;
- prieš ir po buvusia būsena;
- priežasties kodu;
- susijusia konfigūracijos versija.

### FR-LOG-002. Sprendimo rekonstrukcija

Iš saugomų duomenų turi būti įmanoma atkurti, kokią informaciją botas matė
ir kodėl konkrečiu momentu prekiavo arba neprekiavo.

### FR-LOG-003. Nekintami sandorių įrašai

Pirminiai įvykiai netaisomi vietoje. Korekcijos registruojamos nauju įrašu,
išlaikant audit trail.

### FR-LOG-004. Duomenų saugojimas

MVP galima naudoti SQLite, bet turi būti numatyta duomenų migracija ir
atsarginės kopijos. CSV naudojamas eksportui, ne kaip vienintelis tiesos
šaltinis.

## 13. Stebėjimas, perspėjimai ir valdymo skydas

### FR-OBS-001. Sistemos būsena

Valdymo skydas turi rodyti:

- veikimo režimą ir boto būseną;
- brokerio ryšį bei paskutinio tick amžių;
- balance, equity ir dienos/savaitės PnL;
- atvirą riziką;
- aktyvią poziciją ir jos SL/TP;
- dienos sandorių bei nuostolių serijos skaitiklius;
- paskutinį signalą ir atmetimo priežastį;
- aktyvius incidentus ir kill switch būseną.

### FR-OBS-002. Perspėjimai

Perspėjimai siunčiami bent dėl:

- ryšio nutrūkimo;
- neapsaugotos pozicijos;
- pavedimo atmetimo;
- būsenos neatitikimo su brokeriu;
- rizikos limito pasiekimo;
- proceso persikrovimo;
- news ar duomenų šaltinio gedimo;
- live režimo įjungimo ar išjungimo.

### FR-OBS-003. Heartbeat

Sistema periodiškai registruoja gyvybingumo signalą. Jo negavus stebėjimo
modulis perspėja operatorių, net jei pats prekybos procesas nebegali to padaryti.

### FR-OBS-004. Dienos suvestinė

Po sesijos generuojama suvestinė: signalai, atmesti signalai pagal priežastį,
sandoriai, PnL, kaštai, slippage, drawdown, incidentai ir taisyklių pažeidimai.

## 14. Incidentai ir patikimumas

### FR-INC-001. Incidentų klasės

Incidentai skirstomi į `INFO`, `WARNING`, `HIGH` ir `CRITICAL`.
`CRITICAL` automatiškai aktyvuoja `LOCKED` būseną.

### FR-INC-002. Fail-safe elgsena

Nežinoma sistemos būsena, nepavykęs rizikos patikrinimas ar nevalidūs
duomenys reiškia `NO_TRADE`, o ne optimistinį bandymą tęsti.

### FR-INC-003. Atkūrimo procedūra

Po kritinio incidento prekyba neatnaujinama vien dėl proceso perkrovimo.
Reikalinga:

- brokerio ir vietinės būsenos reconciliacija;
- incidento priežasties įrašas;
- operatoriaus patvirtinimas;
- trumpas savikontrolės testas.

### FR-INC-004. Chaos scenarijai

Prieš live režimą testuojami bent šie scenarijai:

- ryšys dingsta prieš ir po pavedimo pateikimo;
- brokeris atsako timeout;
- pavedimas įvykdomas, bet atsakymas negaunamas;
- nepavyksta uždėti SL;
- procesas persikrauna su atvira pozicija;
- pasikeičia brokerio simbolio specifikacija;
- naujienų šaltinis tampa nepasiekiamas;
- sistemos laikrodis ar laiko zona yra neteisinga.

## 15. Saugumas

### FR-SEC-001. Paslapčių saugojimas

Brokerio prisijungimai ir API raktai negali būti laikomi Git ar paprastuose
konfigūracijos failuose. Naudojami aplinkos kintamieji arba secrets saugykla.

### FR-SEC-002. Mažiausios teisės

Jei brokeris leidžia, stebėjimo ir tyrimų procesai naudoja tik skaitymo
teises. Prekybos teisės suteikiamos tik vykdymo komponentui.

### FR-SEC-003. Pavojingų veiksmų patvirtinimas

Live režimo įjungimas, limitų didinimas ir visų pozicijų uždarymas turi būti
aiškiai audituojami ir apsaugoti nuo atsitiktinio paspaudimo.

## 16. Kokybės vartai

### Vartai A: iš BACKTEST į SHADOW

- nėra look-ahead ir duomenų nutekėjimo testų klaidų;
- strategija teigiama po konservatyvių kaštų ne viename periode;
- rezultatas nėra priklausomas nuo vieno parametro taško;
- maksimalus drawdown telpa į patvirtintą rizikos ribą;
- geriausios dienos pašalinimas nesunaikina viso rezultato.

### Vartai B: iš SHADOW į DEMO

- sistema stabiliai veikia be kritinių klaidų;
- visi sprendimai atsekami;
- nėra dubliuotų signalų ar pavedimų;
- spread, sesijų ir naujienų filtrai veikia gyvu laiku;
- būsenos atkūrimo scenarijai ištestuoti.

### Vartai C: iš DEMO į LIVE

- visi demo sandoriai turėjo patvirtintą SL;
- nebuvo rizikos taisyklių apeidimų;
- faktinis execution nuokrypis telpa į testuotą modelį;
- strategijos rezultatas neblogesnis už iš anksto nustatytą stop kriterijų;
- užbaigtas minimalus testavimo laikas per skirtingus rinkos režimus;
- operatorius pasirašo live paleidimo kontrolinį sąrašą.

### Vartai D: live tęstinumas

Live prekyba automatiškai grąžinama į `SHADOW` arba `LOCKED`, jei:

- pasiektas bendras nuostolio limitas;
- execution reikšmingai blogesnis už demo/backtest modelį;
- strategijos rolling metrikos peržengia iš anksto nustatytas ribas;
- atsiranda kritinis techninis incidentas;
- pasikeičia brokerio ar simbolio sąlygos.

## 17. Siūlomas MVP prioritetas

### P0: būtina kapitalo apsaugai

- režimų izoliacija;
- konfigūracijos validavimas;
- brokerio simbolio specifikacijos nuskaitymas;
- risk manager ir mažiausio loto veto;
- pavedimų būsenų mašina ir idempotency;
- privalomas SL;
- kill switch;
- būsenos reconciliacija po perkrovimo;
- struktūrizuotas audito žurnalas.

### P1: būtina eksperimento patikimumui

- bendras strategijos kodas backtest ir forward režimams;
- realistiškas kaštų modelis;
- chronologinis train/validation/test;
- walk-forward ir robustumo ataskaitos;
- shadow režimas;
- dienos suvestinė ir perspėjimai.

### P2: produkto lygio patogumas

- web valdymo skydas;
- kelių strategijų registras;
- eksperimentų palyginimas;
- Monte Carlo ir parametrų heatmap;
- incidentų valdymo ekranas;
- automatinė savaitinė tyrimų ataskaita.

### P3: drąsesnė produkto kryptis

- „digital twin“: gyvo sprendimo lygiagretus atkūrimas keliuose execution
  modeliuose;
- automatinis strategijos degradacijos aptikimas;
- rinkos režimų klasifikatorius su atskira kiekvieno režimo statistika;
- champion/challenger sistema, kur nauja strategija veikia shadow režimu šalia
  dabartinės;
- automatinis duomenų ir brokerio sąlygų pasikeitimo aptikimas;
- paaiškinimų sluoksnis, kuris kiekvieną sandorį pateikia kaip trumpą
  „prekybos kortelę“ su signalu, rizika, kontekstu ir rezultatu;
- „flight recorder“ paketas, leidžiantis vienu veiksmu eksportuoti visus
  incidento duomenis reprodukcijai.

## 18. Siūlomi nefunkciniai reikalavimai

- Rizikos patikrinimas prieš pavedimą: mažiau nei 100 ms, neįskaitant brokerio.
- Jokio kritinio įvykio praradimo proceso perkrovimo metu.
- Visi piniginiai skaičiavimai atliekami be dvejetainio `float` apvalinimo
  klaidų ten, kur reikalingas tikslumas.
- Ne mažiau kaip 90 % testų padengimas risk ir execution moduliams.
- Integraciniai testai su netikru brokeriu visoms pavedimo būsenoms.
- Viena komanda turi atkurti konkretų backtest iš `run_id`.
- Sistema turi gebėti veikti neprižiūrima, bet live režime visada išlaikyti
  žmogaus avarinio sustabdymo galimybę.

## 19. Svarbiausi produkto sprendimai prieš programavimą

Prieš kuriant vykdymo kodą būtina formaliai nuspręsti:

1. Koks tikslus pirmos strategijos aprašas be dviprasmybių?
2. Ar signalas skaičiuojamas pagal tick, M1 ar M5 užbaigtą žvakę?
3. Kokia brokerio simbolio specifikacija ir minimalus lotas?
4. Koks dienos pradžios laikas naudojamas rizikai?
5. Kas laikoma svarbia naujiena ir kas yra patikimas jos šaltinis?
6. Kokia elgsena, jei SL ir TP galėjo būti pasiekti toje pačioje žvakėje?
7. Kokie iš anksto nustatyti strategijos stop ir tęstinumo kriterijai?
8. Kiek laiko strategijos parametrai lieka užšaldyti?
9. Ar live MVP apskritai reikalingas per pirmus tris mėnesius?

Rekomendacija: pirmo trijų mėnesių rezultatu laikyti ne live pelną, o
patikimą `BACKTEST -> SHADOW -> DEMO` grandinę. Į live režimą eiti tik tada,
kai brokerio minimalus lotas leidžia tiksliai laikytis rizikos ir sukaupta
pakankamai duomenų per daugiau nei vieną rinkos režimą.

## 20. Frontend valdymo platforma

Sistema turi turėti konfigūruojamą web frontend, skirtą ne vienai fiksuotai
boto kopijai, o kelioms nepriklausomoms instancijoms valdyti.

Kiekvienai instancijai atskirai priskiriama:

- brokerio sąskaita;
- veikimo režimas;
- instrumentas ir timeframe;
- strategijos bei jos parametrų versija;
- rizikos profilis;
- filtrai ir prekybos sesijos;
- perspėjimų nustatymai;
- paleidimo ir rezultatų istorija.

Frontend apima:

- bendrą Command Center;
- botų kūrimą, klonavimą ir versijuotą konfigūravimą;
- realaus laiko stebėjimą;
- signalų, pavedimų, pozicijų ir sandorių peržiūrą;
- portfelio rizikos kontrolę;
- backtest laboratoriją;
- išsamią analitiką ir botų palyginimą;
- duomenų tyrimą bei eksportą;
- incidentų ir ataskaitų valdymą;
- naudotojų roles ir pavojingų veiksmų auditą.

Detalus ekranų, objektų, navigacijos, analitikos, UX, API ribų ir acceptance
criteria modelis aprašytas dokumente
`xauusd_trading_bot_ui_modelis.md`.

## 21. Technologijų architektūra

Rekomenduojamas technologijų, komponentų, duomenų saugojimo, testavimo,
hostingo ir diegimo modelis aprašytas dokumente
`xauusd_trading_bot_technologiju_architektura.md`.
