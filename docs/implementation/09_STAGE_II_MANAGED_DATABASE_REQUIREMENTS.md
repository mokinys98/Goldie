# II etapas: valdoma internetinė duomenų bazė

Dokumento data: 2026-06-11. Kainos yra preliminarios, nurodytos be PVM ir
prieš pirkimą turi būti patikrintos tiekėjo puslapyje.

## Sprendimas

Goldie jau naudoja PostgreSQL 17, SQLAlchemy, Alembic migracijas ir `psycopg`.
Todėl II etapui nereikia keisti duomenų bazės technologijos. Reikia vietinį
Docker PostgreSQL pakeisti valdoma PostgreSQL paslauga internete.

Rekomenduojamas pradinis variantas:

- valdoma PostgreSQL paslauga ES regione;
- mokamas pradinis planas, ne nemokamas produkcinis planas;
- 10 GB pradinė talpa su automatiniu didinimu;
- bent 0,25 vCPU / 1 GB RAM ekvivalentas, leidžiantis didinti resursus;
- kasdienės automatinės kopijos, saugomos bent 7 dienas;
- TLS ryšys ir atskiri produkciniai prisijungimo duomenys;
- numatomas DB biudžetas: 20-35 USD per mėnesį;
- 3 mėnesių DB biudžetas: 60-105 USD be PVM.

Praktinis pirmas pasirinkimas: **Neon Launch** arba lygiavertė valdoma
PostgreSQL paslauga ES regione. Alternatyva su aiškesne fiksuota mėnesio
kaina ir papildomomis platformos funkcijomis: **Supabase Pro**.

## Kodėl nepalikti DB namų kompiuteryje

Vietinė DB priklauso nuo vieno kompiuterio, interneto ryšio, elektros ir
rankinių kopijų. Valdoma DB suteikia stabilų adresą, TLS, stebėseną,
automatines kopijas ir galimybę API serveriui prisijungti nepriklausomai nuo
to, iš kur vartotojas atidaro Goldie.

Naršyklė ir MT5 agentas neturi jungtis tiesiai prie DB. Ryšio schema:

```text
Naršyklė / MT5 agentas -> HTTPS/WSS -> Goldie API -> TLS -> PostgreSQL
```

Vien internetinės DB pirkimas nepadarys `localhost:3000` pasiekiamo iš kitų
vietų. Tam pačiu etapu reikės internete talpinti bent Goldie API ir Web UI
arba įrengti saugų VPN priėjimą prie jų.

## Minimalūs pirkimo reikalavimai

### Suderinamumas

- PostgreSQL 16 arba 17.
- Pilnas SQL prisijungimas per standartinę PostgreSQL jungties eilutę.
- Suderinamumas su `psycopg`, SQLAlchemy ir Alembic.
- Palaikomos UUID, `numeric`, `json/jsonb`, laiko zonos ir indeksai.
- Galimybė paleisti migracijas iš API diegimo aplinkos.
- Tiek tiesioginis, tiek connection pooler prisijungimas.

### Regionas ir našumas

- ES duomenų centras, pageidautina Frankfurtas ar kitas geografiškai artimas
  ES regionas.
- Pradinė skaičiavimo galia: bent 0,25 vCPU / 1 GB RAM ekvivalentas.
- Bent 20 vienalaikių DB jungčių arba pooler, palaikantis didesnį klientų
  skaičių.
- Automatinis disko didinimas arba aiški galimybė padidinti iki 25 GB be
  migracijos.
- Matomi CPU, RAM, disko, jungčių ir užklausų rodikliai.

### Talpa trims mėnesiams

Didžiausią augimą sudarys `market_ticks`. Jei įrašomas vienas tick per
sekundę, 23 valandas per parą ir 5 dienas per savaitę, susidaro apie
1,8 mln. eilučių per mėnesį. Įvertinus indeksus ir DB režijines sąnaudas,
pradiniam etapui tikslinga planuoti apie 1 GB per mėnesį.

- Bazinis scenarijus: 10 GB trims mėnesiams.
- Jei registruojama apie 5 tick per sekundę: rinktis 20-25 GB arba trumpinti
  neapdorotų tick saugojimo laiką.
- Po pirmos savaitės pamatuoti faktinį `market_ticks` dydį ir perskaičiuoti
  90 dienų prognozę.
- Pradinis retention siūlymas: raw tick laikyti 30 dienų, o žvakes, signalus,
  konfigūracijas ir audito įrašus laikyti visus 3 mėnesius.

### Saugumas

- Privalomas TLS (`sslmode=require` arba tiekėjo nurodytas griežtesnis
  režimas).
- DB slaptažodžiai saugomi tik hostingo secrets / environment variables,
  ne Git repozitorijoje.
- Atskiri vartotojai programai ir administravimui.
- Programos vartotojui nesuteikiamos superuser teisės.
- Įjungtas MFA tiekėjo paskyrai.
- Jei planas leidžia, API serverio IP įtraukiamas į allowlist.
- DB nėra naudojama kaip vieša API ir jos prisijungimo eilutė nepatenka į
  `NEXT_PUBLIC_*` kintamuosius.

### Kopijos ir atkūrimas

- Automatinė kopija bent kartą per parą.
- Bent 7 dienų atkūrimo istorija.
- Bent kartą per savaitę atskiras loginis `pg_dump`, laikomas ne pas tą patį
  DB tiekėją.
- Prieš paleidimą atliekamas bandomasis atkūrimas į atskirą DB.
- Pradinis tikslas: RPO iki 24 val., RTO iki 4 val.

## Tiekėjų orientyras

### Neon Launch

- Mokama pagal naudojimą, oficialus tipinis mažos protarpinės DB pavyzdys yra
  apie 15 USD/mėn.
- 7 dienų point-in-time / time-travel atkūrimo langas.
- Saugykla ir skaičiavimo resursai didinami pagal naudojimą.
- Nuolat gaunant rinkos duomenis DB gali neužmigti, todėl realistiškesnis
  Goldie biudžetas yra apie 20-25 USD/mėn., ne minimalus pavyzdys.

### Supabase Pro

- Pro plano bazė yra 25 USD/mėn.; vienam mažam projektui įskaičiuojami
  compute kreditai.
- Pro projektams teikiamos kasdienės kopijos ir 7 dienų istorija.
- Patogu, jei vėliau bus naudojamos papildomos Supabase funkcijos, tačiau
  dabartiniam Goldie API jos nėra būtinos.

Nemokamas planas tinka tik bandymams. Produkciniam 3 mėnesių etapui jis
nerekomenduojamas dėl mažesnių garantijų, ribotų kopijų ir galimo stabdymo.

## Priėmimo kriterijai

- API ir worker naudoja vieną produkcinį `DATABASE_URL` su TLS.
- Alembic migracija `0001` sėkmingai įvykdoma tuščioje nuotolinėje DB.
- Vietinis PostgreSQL konteineris nėra būtinas produkciniam darbui.
- Prisijungus iš kito tinklo galima autentifikuotis Goldie UI ir matyti tuos
  pačius duomenis.
- MT5 agentas gali siųsti duomenis į viešą HTTPS API.
- DB nėra tiesiogiai pasiekiama naršyklės kodui.
- Veikia automatinės kopijos ir dokumentuotas atkūrimo bandymas.
- Nustatyti išlaidų perspėjimai ties 25 ir 35 USD per mėnesį.

## Pirkimo kontrolinis sąrašas

- Pasirinktas ES regionas.
- Patikrinta PostgreSQL versija ir TLS jungties eilutė.
- Patikrintas 7 dienų arba ilgesnis backup/restore langas.
- Nustatytas mėnesio išlaidų limitas arba perspėjimas.
- Patikrinta, ar egress, IPv4, PITR ir papildoma saugykla nekainuoja atskirai.
- Užregistruota paskyra su MFA ir atsiskaitymo duomenimis.
- Išsaugoti avarinio atkūrimo kontaktai ir tiekėjo statuso puslapis.

## Šaltiniai

- Neon kainos: https://neon.com/pricing
- Supabase kainos: https://supabase.com/pricing
- Supabase compute kainodara:
  https://supabase.com/docs/guides/platform/manage-your-usage/compute
- Supabase atsarginės kopijos:
  https://supabase.com/docs/guides/platform/backups

