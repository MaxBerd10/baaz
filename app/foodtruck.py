"""Food truck ishlab chiqarish uchun standart bosqichlar va QC tekshiruv ro'yxati."""
from __future__ import annotations

# (order_no, nom, tavsif, [tekshiruv punktlari])
STAGES: list[tuple[int, str, str, list[str]]] = [
    (
        1,
        "Shassi va rama",
        "Pritsep/shassi tayyorlash, ramka payvandlash, o'qlar, ressora, gorizontal tekislash.",
        [
            "Payvand choklari to'liq va yorilishsiz",
            "Rama diagonallari teng (to'g'riburchak)",
            "O'qlar va ressora mahkam, lyuft yo'q",
            "Zang tozalangan, gruntlangan",
            "Rama o'lchamlari chizmaga mos",
            "Tortish qurilmasi (fartsep) va tormoz tekshirildi",
        ],
    ),
    (
        2,
        "Korpus va karkas",
        "Devor va tom karkasi, eshik-deraza o'yiqlari, metall skelet.",
        [
            "Karkas to'g'riburchak va vertikal",
            "Eshik/deraza o'yiqlari o'lchamlari spetsifikatsiyaga mos",
            "Payvand nuqtalari mustahkam",
            "Kuchlanish joylari (jihoz osiladigan) kuchaytirilgan",
            "Pol asosi tekis va mahkam",
        ],
    ),
    (
        3,
        "Izolyatsiya va tashqi qoplama",
        "Issiqlik izolyatsiyasi, sendvich-panel/list qoplash, germetizatsiya, tom suvo'tkazmasligi.",
        [
            "Izolyatsiya bo'shliqsiz, to'liq qoplangan",
            "Tashqi panellar tekis va tutash",
            "Barcha choklar germetiklangan",
            "Tom suv o'tkazmaydi (suv sinovi)",
            "Eshik/deraza o'rnatilgan va zich yopiladi",
        ],
    ),
    (
        4,
        "Suv va gaz tizimi",
        "Toza/iflos suv baklari, rakovina, LPG quvurlari, reduktor, bosim sinovi.",
        [
            "Suv baklari mahkam, sizish yo'q",
            "Nasos va rakovinalar ishlaydi, drenaj to'g'ri",
            "Gaz quvurlari sertifikatlangan fitinglar bilan",
            "Gaz bosim sinovi o'tdi (belgilangan vaqt ushlab turildi)",
            "Sovunli sinov — gaz sizishi yo'q",
            "Avariya gaz krani va ventilyatsiya mavjud",
            "Ballon bo'limi ajratilgan va shamollaydigan",
        ],
    ),
    (
        5,
        "Elektr tizimi",
        "Simlar, avtomat shchit, rozetkalar, akkumulyator/invertor/tashqi ta'minot, yoritish.",
        [
            "Simlar kesimi yuklamaga mos, izolyatsiya butun",
            "Zazemleniye (yer) barcha metall qismlarga ulangan",
            "UZO/differensial avtomat sinovda ishladi",
            "Avtomatlar nominali to'g'ri, zanjirlar belgilangan",
            "Tashqi 220V kirish va akkumulyator/invertor ishlaydi",
            "Yoritish va rozetkalar yuklamada sinovdan o'tdi",
        ],
    ),
    (
        6,
        "Oshxona jihozlarini o'rnatish",
        "Plita/fritür, so'rg'ich zont va ventilyator, muzlatgich, ish stollari, yong'in o'chirish tizimi.",
        [
            "Jihozlar mahkamlangan, harakatda siljimaydi",
            "So'rg'ich zont havo oqimi yetarli (o'lchov)",
            "Yonuvchan yuzalardan xavfsiz masofa saqlangan",
            "Gaz jihozlari ulangan va sizishsiz",
            "Yong'in o'chirish tizimi o'rnatilgan va sertifikatlangan",
            "Ish yuzalari gigiyenik (choksiz, oson tozalanadi)",
            "Muzlatgich harorati normal ishlaydi",
        ],
    ),
    (
        7,
        "Yakuniy jihozlash va sinov",
        "Brending/plyonka, ichki bezak, tozalash, barcha tizimlarni to'liq sinash, yo'l sinovi, hujjatlar.",
        [
            "Tashqi ko'rinish/plyonka toza va nuqsonsiz",
            "Barcha tizimlar bir vaqtda ishlashda sinovdan o'tdi",
            "Yo'l sinovi o'tkazildi (tormoz, chiroqlar, tebranish)",
            "Umumiy og'irlik va o'qqa yuklama me'yorda",
            "Hujjatlar to'liq (sertifikatlar, kafolat, instruksiya)",
            "Yakuniy tozalash bajarildi",
            "Mijozga topshirishga tayyor",
        ],
    ),
]
