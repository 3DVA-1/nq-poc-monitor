# NQ stebėtojas — tavo POC indikatorius ir Gmail laiškai

Programa gauna vėluojančias NQ 15 min. žvakes iš „Yahoo Finance“, perskaičiuoja tavo „Volume Profile / Fixed Range“ ir siunčia laišką, kai kaina pakeičia pusę POC linijos atžvilgiu. Pradiniai nustatymai tokie patys: **150 žvakių, 24 eilutės, 70 % Value Area**. Tai nėra visa prekybos ar grafiko platforma; indikatoriaus skaičiavimas naudojamas perspėjimui.

## Kada ateina laiškas

- Į viršų: ankstesnis užsidarymas buvo ties ankstesniu POC arba žemiau; naujas užsidarymas yra virš naujo POC.
- Į žemyn: ankstesnis užsidarymas buvo ties ankstesniu POC arba aukščiau; naujas užsidarymas yra žemiau naujo POC.
- POC perskaičiuojamas, todėl signalą gali sukelti ir pačios linijos judėjimas.
- Tikrinamos baigtos 15 min. žvakės pagal konservatyvią laiko taisyklę. Kadangi tiekėjas neduoda patikimo „galutinė žvakė“ žymeklio, laukiama bent **15 min. po žvakės pabaigos ir dar 1 min. atsargos**. Tai apsauga, o ne garantija, kad šaltinis nepatikslins duomenų.
- Debesijos patikrinimas vyksta kas 15 min. Todėl laiškas paprastai gali ateiti 16–31 min. arba dar vėliau po žvakės pabaigos. „GitHub“ vykdymas gali papildomai vėluoti arba būti praleistas.
- Pirmas paleidimas įsimena dabartinę padėtį ir nesiunčia senų signalų. Naujos konfigūracijos taip pat pradedamos be istorinių laiškų.
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

1. „Actions“ pasirink **NQ POC el. pastas → Run workflow**.
2. Pažymėk **Siusti tik bandomaji laiska** ir paleisk. Patikrink Gmail, įskaitant šlamšto aplanką. Tai tik bandomasis laiškas.
3. Dar kartą paleisk tą pačią darbo eigą, šį kartą be bandomojo laiško žymos. Pirmas rinkos patikrinimas sukurs `state/` pažangos failą.
4. Žurnale turi būti „First run: baseline recorded“ ir baigtų žvakių bei POC reikšmės. „GitHub“ turi įrašyti „Save NQ monitoring progress“ pakeitimą.
5. Po to grafikas vykdomas automatiškai 7, 22, 37 ir 52 minutę kiekvieną valandą (UTC). Kompiuterį gali išjungti.
6. Žalia „Actions“ būsena patvirtina vykdymą, bet ne rinkos duomenų šviežumą. Žurnale visada matysi naujausios apdorotos žvakės laiką. Uždarytoje rinkoje jis natūraliai senesnis.

Privati saugykla: nemokamos minutės ribotos. Kas 15 min. sudaro maždaug 2 880 paleidimų per 30 dienų ir gali viršyti nemokamą kvotą. Nemokamam bandymui pakeisk darbo eigos `cron` į `7,37 * * * *` (kas 30 min., apie 1 440 paleidimų per 30 dienų). Minutės priklauso nuo tikros vykdymo trukmės ir kitų tavo darbo eigų, todėl stebėk „Billing and licensing“ naudojimą ir neįjunk mokamo viršijimo, jei jo nenori. Viešą darbo eigą „GitHub“ gali automatiškai išjungti po 60 dienų be saugyklos veiklos; ši programa įrašo pažangą, bet vis tiek tikrink jos būseną.

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

Tikras vietinis siuntimas reikalauja aplinkos kintamųjų `GMAIL_USER`, `GMAIL_APP_PASSWORD`, `ALERT_EMAIL`. Juos nustatyk savo aplinkoje. Vienas patikrinimas: `python monitor.py --once`. Bandomasis laiškas: `python monitor.py --test-email`. Atstatymas: `python monitor.py --once --reset-state` — pašalina tos konfigūracijos laukiančius signalus ir pradeda nuo naujo atskaitos taško. Vienu metu naudok vieną vykdytoją ir išsaugok `state/` tarp paleidimų.

## Patikros būsena

Viešų NQ žvakių gavimas ir POC apskaičiavimas patikrinti vietoje. Automatiniai testai tikrina apimties paskirstymą, kirtimus, užsidarymą, pažangą ir pakartotinį siuntimą. Tikras Gmail siuntimas ir GitHub debesijos veikimas turi būti patikrinti tavo paskyrose; šiame pakete nėra prisijungimo duomenų, o debesijos stebėjimas dar neaktyvuotas.

## Oficialūs šaltiniai

- [Yahoo NQ: vėluojančios kotiruotės](https://finance.yahoo.com/quote/NQ%3DF/)
- [Gmail programų slaptažodžiai](https://support.google.com/mail/answer/185833)
- [GitHub Actions naudojimas ir mokėjimas](https://docs.github.com/en/actions/concepts/billing-and-usage)
- [GitHub grafikų vėlavimas ir ribojimai](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [GitHub Secrets](https://docs.github.com/en/actions/concepts/security/secrets)
