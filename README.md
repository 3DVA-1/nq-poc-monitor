# NQ stebėtojas — tavo POC indikatorius ir Gmail laiškai

Programa gauna vėluojančias NQ **15 min. ir 1H** žvakes iš „Yahoo Finance“, kiekvienam intervalui atskirai perskaičiuoja tavo „Volume Profile / Fixed Range“ ir siunčia laišką, kai kaina pakeičia pusę POC linijos atžvilgiu. Abiem intervalams naudojami tavo nustatymai: **150 žvakių, 24 eilutės, 70 % Value Area**. 1H profilis skaičiuojamas iš 150 valandinių žvakių, o 15 min. profilis — iš 150 penkiolikos minučių žvakių. Laiško temoje ir tekste nurodomas signalo intervalas.

`config.json` laukelis `"timeframes": ["15m", "1h"]` įjungia abu intervalus. Galima palikti tik vieną iš jų. Senesnė konfigūracija be šio laukelio stebi tik 15 min. grafiką.

## Kada ateina laiškas

- Į viršų: ankstesnis užsidarymas buvo ties ankstesniu POC arba žemiau; naujas užsidarymas yra virš naujo POC.
- Į žemyn: ankstesnis užsidarymas buvo ties ankstesniu POC arba aukščiau; naujas užsidarymas yra žemiau naujo POC.
- POC perskaičiuojamas, todėl signalą gali sukelti ir pačios linijos judėjimas.
- Tikrinamos tik užsidariusios kiekvieno intervalo žvakės pagal laiko taisyklę: „Yahoo“ [CME kotiruotėms nurodo 10 min. vėlavimą](https://help.yahoo.com/kb/yahoo-finance-plus/partnerships-sln2310.html), todėl laukiama bent **10 min. po žvakės pabaigos ir dar 1 min. atsargos**. 1H žvakė vertinama tik pasibaigus visai jos valandai. Tiekėjas neduoda patikimo „galutinė žvakė“ žymeklio, todėl tai laiko prielaida, o ne garantija, kad šaltinis nepatikslins duomenų.
- Papildomos momentinės kotiruotės, kurių pradžios laikas nesutampa su 15 min. arba 1H žvakės riba, atmetamos. `NQ=F` taip pat atmetamos eilutės už įprastos savaitinės CME sesijos: penktadienį nuo 17:00 iki sekmadienio 18:00 ir kasdien per 17:00–18:00 pertrauką Niujorko laiku. Naudojama `America/New_York` laiko juosta, todėl atsižvelgiama į vasaros laiką. Tai įprastos savaitės filtras, ne švenčių ir išimtinių biržos uždarymų kalendorius. Vien nulinis tūris nėra priežastis atmesti tinkamo laiko žvakę.
- Abiejų intervalų patikrinimas suplanuotas kas 15 min., 12, 27, 42 ir 57 minutę kiekvieną valandą (UTC), apie **12 min. po įprastos 15 min. arba 1H žvakės pabaigos**. Gavus signalą, tada bandoma siųsti laišką. „GitHub“ vykdymas gali papildomai vėluoti arba būti praleistas, o duomenų šaltinis gali atnaujinti ar patikslinti žvakes vėliau.
- Kiekvienas intervalas turi atskirą pažangą ir laukiančius laiškus. Pirmas jo paleidimas įsimena dabartinę padėtį ir nesiunčia senų signalų. Pridėjus 1H, esama 15 min. pažanga išlaikoma; tik naujasis 1H intervalas pradeda nuo dabartinės vietos. Nauji profilio nustatymai taip pat pradedami be istorinių laiškų.
- Jei ankstesnė programos versija įsiminė netinkamo laiko `NQ=F` eilutę, turint pakankamai tinkamų užsidariusių žvakių atkuriamas atskaitos taškas ties naujausia iš jų. Taisymo metu istoriniai signalai nesiunčiami; tinkamų žvakių laukiantys laiškai išlaikomi, o aiškiai netinkamo laiko įvykiai atmetami. Įprastas tinkamo laiko atskaitos taškas dėl senesnio tiekėjo atsakymo nenustatomas iš naujo — toks atsakymas tebėra klaida.
- Po sutrikimo aptinkami neperskaityti signalai, bet senesni nei 90 min. nebesiunčiami.
- SMTP klaidos atveju signalas išsaugomas ir bandomas vėliau. Pakartotinis siuntimas vykdomas, kai pavyksta ir rinkos duomenų užklausa; ilgas duomenų sutrikimas gali atidėti laišką iki jo galiojimo pabaigos. Po neaiškaus ryšio nutrūkimo retai galimas pakartotinis laiškas, nes SMTP negali užtikrinti vienintelio pristatymo.

## Paleidimas debesijoje: tavo kompiuterio nereikės

### 1. Paruošk Gmail

1. Savo „Google“ paskyroje įjunk dviejų žingsnių patvirtinimą.
2. Atidaryk [Programų slaptažodžius](https://myaccount.google.com/apppasswords).
3. Sukurk naują slaptažodį, pavadinęs programą „NQ stebėtojas“.
4. Gautą programos slaptažodį įrašysi į „GitHub Secret“. **Į pokalbį ir į kodo failus jo nerašyk.** Naudojamas programos, ne įprastas „Gmail“ slaptažodis. Kai kurios paskyros šios funkcijos neturi; žr. [Google instrukciją](https://support.google.com/mail/answer/185833).

### 2. Paruošk GitHub projektą

1. Savo „GitHub“ paskyroje sukurk naują saugyklą, pvz., `nq-poc-monitor`.
2. Nemokamam tikrinimui kas 15 min. pasirink **Public**: šios saugyklos programos kodas, rinkos signalų laikas, POC ir vykdymo žurnalai bus vieši. „Gmail“ duomenys laikomi „Secrets“ ir į kodą nepatenka. Viešos saugyklos standartiniai „GitHub Actions“ vykdytojai yra nemokami. Jei nenori viešinti kodo, rinkis **Private** ir retesnį grafiką, kaip aprašyta žemiau.
3. Išarchyvuok paketą ir į saugyklos pagrindą įkelk **NQ_Stebetojas aplanko turinį**, ne patį ZIP ir ne papildomą aplanko lygį. Saugyklos pagrinde turi būti `monitor.py`, `volume_profile.py`, `config.json`, `requirements.txt`, `tests/` ir `.github/workflows/nq-monitor.yml`.
4. `.github` yra paslėptas aplankas. Jei įkeli per naršyklę, darbo eigos failą gali sukurti atskirai per „Add file → Create new file“, pavadinęs `.github/workflows/nq-monitor.yml` ir nukopijavęs jo turinį.
5. Įjunk „Actions“, jei „GitHub“ paprašys. „Settings → Actions → General → Workflow permissions“ pasirink **Read and write permissions**, kad programa galėtų išsaugoti pažangą.

### 3. Įrašyk tris Secrets

Saugykloje: **Settings → Secrets and variables → Actions → New repository secret**.

| Secret pavadinimas | Reikšmė |
|---|---|
| `GMAIL_USER` | Tavo laiškus siunčiančios Gmail paskyros adresas |
| `GMAIL_APP_PASSWORD` | Sukurtas Gmail programos slaptažodis |
| `ALERT_EMAIL` | Adresas, kuriuo gauti laiškus; gali būti kita Gmail paskyra, skirtinga nuo siunčiančios paskyros |

Jeigu `ALERT_EMAIL` nepateiksi, laiškai siunčiami į `GMAIL_USER`.

### 4. Patikrink ir aktyvuok

Pasirenkamas duomenų patikrinimas prieš įrašant „Gmail“ programos slaptažodį: „Actions → NQ POC el. pastas → Run workflow“ pažymėk **Patikrinti duomenis be laisku ir be pazangos issaugojimo**. Šis bandymas gauna NQ žvakes ir parodo POC, nereikalauja „Gmail“ prisijungimo, nesiunčia laiškų ir neišsaugo pažangos. Jei pažymėtos abi bandymo parinktys, pirmenybė teikiama duomenų patikrinimui ir laiškas nesiunčiamas. Tikram stebėjimui šią parinktį išjunk.

1. „Actions“ pasirink **NQ POC el. pastas → Run workflow**.
2. Pažymėk **Siusti tik bandomaji laiska** ir paleisk. Patikrink Gmail, įskaitant šlamšto aplanką. Tai tik bandomasis laiškas.
3. Dar kartą paleisk tą pačią darbo eigą, šį kartą išjungęs abi bandymo parinktis. Pirmas rinkos patikrinimas sukurs atskirą `state/` pažangos failą kiekvienam intervalui.
4. Žurnale turi būti abiejų intervalų patikrinimai ir jų baigtų žvakių bei POC reikšmės. „First run: baseline recorded“ rodomas tik pirmą kartą pradėtam intervalui. „GitHub“ turi įrašyti „Save NQ monitoring progress“ pakeitimą. Vieno intervalo duomenų ar siuntimo klaida netrukdo pabandyti patikrinti kitą intervalą; bendras vykdymas vis tiek pažymimas nesėkmingas, kad sutrikimas būtų matomas.
5. Po to grafikas vykdomas automatiškai 12, 27, 42 ir 57 minutę kiekvieną valandą (UTC). Kompiuterį gali išjungti.
6. Žalia „Actions“ būsena patvirtina vykdymą, bet ne rinkos duomenų šviežumą. Žurnale visada matysi naujausios apdorotos žvakės laiką. Uždarytoje rinkoje jis natūraliai senesnis.

Privati saugykla: nemokamos minutės ribotos. Kas 15 min. sudaro maždaug 2 880 paleidimų per 30 dienų ir gali viršyti nemokamą kvotą. Nemokamam bandymui pakeisk darbo eigos `cron` į `12,42 * * * *` (kas 30 min., apie 1 440 paleidimų per 30 dienų). Minutės priklauso nuo tikros vykdymo trukmės ir kitų tavo darbo eigų, todėl stebėk „Billing and licensing“ naudojimą ir neįjunk mokamo viršijimo, jei jo nenori. Viešą darbo eigą „GitHub“ gali automatiškai išjungti po 60 dienų be saugyklos veiklos; ši programa įrašo pažangą, bet vis tiek tikrink jos būseną.

Išjungimas: „Actions → NQ POC el. pastas → ... → Disable workflow“. Google programos slaptažodį galima atšaukti „Google“ paskyroje.

## Duomenų ir TradingView skirtumai

Numatytas simbolis **NQ=F** yra „Yahoo“ artimiausio kontrakto seka. Kontraktas, sesija, apimtis ir perėjimas į kitą kontraktą gali skirtis nuo tavo „TradingView“ grafiko, todėl identiškų signalų nežadama. Jei nori konkretaus kontrakto, `config.json` įrašyk tinkamą Yahoo simbolį; patikrink, kad jo chart užklausa grąžina duomenis. Automatinis kontrakto pasikeitimo aptikimas pagal aprašą yra tik papildoma pagalba. Aplink kontraktų pasikeitimą gali reikėti iš naujo nustatyti atskaitos tašką.

POC skaičiavimo metodas atitinka tavo atsiųstą kodą: žvakės kūno apimtis paskirstoma svoriu 1, dagčių — svoriu 2; pasirenkama pirmoji didžiausios apimties eilutė, o lygių kaimyninių apimčių atveju Value Area plečiama aukštyn. Nulinio diapazono arba netinkami duomenys nesukelia signalų. Spalvų ir profilio stačiakampių ši programa nepiešia.

„Yahoo“ viešas duomenų gavimo adresas nėra garantuota oficiali API paslauga: jis gali grąžinti 429, neveikti arba pakeisti formatą. Programa tokiu atveju baigia patikrinimą su klaida; būsimas grafiko vykdymas bando iš naujo. Ji neapeina prieigos ribojimų. Dalinai trūkstama žvakė sustabdo signalus, kuriems jos reikia; visai tuščia tiekėjo eilutė laikoma tarpu be prekybos, nors vien iš jos neįmanoma atmesti duomenų trūkumo. Pirmą signalą palygink su savo grafiku.

## Paleidimas kompiuteryje (pasirenkamas)

Reikia Python 3.12 arba naujesnio. Terminale šiame aplanke:

```powershell
python -m pip install -r requirements.txt
python monitor.py --dry-run
python -m unittest discover -s tests -v
```

`--dry-run` tik gauna duomenis ir parodo POC; nieko nesiunčia ir neišsaugo pažangos. „Gmail“ prisijungimo jam nereikia.

Tikras vietinis siuntimas reikalauja aplinkos kintamųjų `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_EMAIL`. Juos nustatyk savo aplinkoje. Vienas abiejų intervalų patikrinimas: `python monitor.py --once`. Bandomasis laiškas: `python monitor.py --test-email` — siunčiamas vienas testinis laiškas. Atstatymas: `python monitor.py --once --reset-state` — pašalina visų konfigūracijoje pasirinktų intervalų laukiančius signalus ir pradeda juos nuo naujo atskaitos taško. Vienu metu naudok vieną vykdytoją ir išsaugok `state/` tarp paleidimų.

## Patikros būsena

Automatiniai testai tikrina apimties paskirstymą, kirtimus, 15 min. ir 1H žvakių užsidarymą, atskirą pažangą, senų 15 min. būsenų suderinamumą ir pakartotinį siuntimą. Viešų žvakių gavimą patikrink su `--dry-run`, o tikrą laiškų siuntimą ir pažangos išsaugojimą — savo „GitHub Actions“ žurnaluose. Šiame pakete nėra prisijungimo duomenų.

## Oficialūs šaltiniai

- [Yahoo NQ: vėluojančios kotiruotės](https://finance.yahoo.com/quote/NQ%3DF/)
- [Yahoo biržų duomenų vėlavimas: CME 10 min.](https://help.yahoo.com/kb/yahoo-finance-plus/partnerships-sln2310.html)
- [Gmail programų slaptažodžiai](https://support.google.com/mail/answer/185833)
- [GitHub Actions naudojimas ir mokėjimas](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub grafikų vėlavimas ir ribojimai](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Secrets](https://docs.github.com/en/actions/concepts/security/secrets)
