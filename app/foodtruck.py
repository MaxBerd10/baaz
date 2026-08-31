"""Food truck ishlab chiqarish liniyalari va QC tekshiruv ro'yxati.

6 ta ish liniyasi ketma-ket. Liniya 6 tugagach truck "Tayyor" holatiga o'tadi
(alohida bosqich emas — tugash belgisi)."""
from __future__ import annotations

# (order_no, nom, tavsif, [tekshiruv punktlari])
STAGES: list[tuple[int, str, str, list[str]]] = [
    (
        1,
        "Karkas",
        "Truck karkasini (skeletini) payvandlash — asosiy metall konstruksiya.",
        [
            "Payvand choklari to'liq va yorilishsiz",
            "Karkas diagonallari teng (to'g'riburchak)",
            "O'lchamlar chizmaga mos (model bo'yicha)",
            "Zang tozalangan, gruntlangan",
            "Kuchlanish joylari (jihoz osiladigan) kuchaytirilgan",
            "Pol asosi tekis va mahkam",
        ],
    ),
    (
        2,
        "Kuzov o'rnatish",
        "Karkas ustiga kuzov (devor va tom panellari) o'rnatiladi.",
        [
            "Kuzov karkasga mahkam biriktirilgan",
            "Devorlar vertikal, tom gorizontal",
            "Panel choklari zich, bo'shliqsiz",
            "Eshik/deraza o'yiqlari o'lchami model spetsifikatsiyasiga mos",
            "Tom suv oqishi uchun qiyalik to'g'ri",
        ],
    ),
    (
        3,
        "Ichki addelka",
        "Ichki bezak: izolyatsiya, qoplama, pol, shift, ichki panellar.",
        [
            "Issiqlik izolyatsiyasi bo'shliqsiz qoplangan",
            "Ichki qoplama tekis, choksiz (gigiyenik)",
            "Pol qoplamasi mustahkam va suv o'tkazmaydi",
            "Shift panellari mahkam",
            "Simlar/quvurlar uchun kanallar tayyor",
        ],
    ),
    (
        4,
        "Malyarka",
        "Bo'yash va kraska ishlari — tashqi va ichki yuzalar.",
        [
            "Yuza tozalangan, gruntlangan, silliqlangan",
            "Rang mijoz buyurtmasiga mos",
            "Bo'yoq bir tekis, dog' va oqma yo'q",
            "Qirralar va burchaklar to'liq bo'yalgan",
            "Quritish rejimi bajarilgan",
        ],
    ),
    (
        5,
        "Eshik-deraza",
        "Eshik va derazalarni o'rnatish, germetizatsiya, mexanizmlar.",
        [
            "Eshiklar to'g'ri o'rnatilgan, zich yopiladi",
            "Derazalar germetik, suv o'tkazmaydi",
            "Petlya va qulflar ishlaydi",
            "Rezina uplotnitellar butun",
            "Ochish-yopish silliq, qiyshiqlik yo'q",
        ],
    ),
    (
        6,
        "Zborka",
        "Yakuniy yig'ish: payvand ishlari, jihozlarni o'rnatish, ichki jihozlash, sinov.",
        [
            "Barcha jihozlar mahkamlangan, siljimaydi",
            "Payvand/mahkamlash nuqtalari mustahkam",
            "Elektr va suv tizimlari ulangan va sinovdan o'tgan",
            "Ichki jihozlar (stol, javon, rakovina) o'rnatilgan",
            "Umumiy tozalash bajarilgan",
            "Yakuniy ko'zdan kechirish — mijozga topshirishga tayyor",
        ],
    ),
]

# O'lcham (metr) tugmalari
SIZES = [3, 4, 5, 6, 7]
