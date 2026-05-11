"""
engine_config.py
================
Motor-spesifik bilgiler. Sadece bu dosyayı değiştirerek farklı motora uyarlayın.

Motor: 4-zamanlı, 4-silindirli, redüksiyon dişlili havacılık motoru
Redüksiyon oranı: 0.59:1

NOT — Motor bilgileri (dişli diş sayıları, tam devir aralığı, ateşleme
sırası) henüz teyit edilmemiştir. Doğru değerleri öğrenince bu dosyayı
güncelleyin; kodun başka hiçbir yerine dokunmanız gerekmez.

RPM KAYNAĞI UYARISI
────────────────────
Tachometer sinyali yoktur. DEWESoft'ta yanma orderından (2x) RPM geri
hesaplanmaktadır. Bu yöntem:
  - Yanma anomalisi olan motorda yanlış RPM verir.
  - Tüm order analizinde sistematik kaymaya yol açar.
ÇÖZÜM: Sabit devir noktalarında (2000, 2300, 2500 RPM gibi) ölçüm alın
ve o devri DEWESoft'a manuel sabit değer olarak girin.

SENSÖR KANALI = LOKASYON + EKSEN
──────────────────────────────────
Her kanal bağımsız analiz edilir. Referans da kanal bazındadır.
Toplam 18 kanal: 6 lokasyon × 3 eksen (X, Y, Z)

DOSYA İSİMLENDİRME STANDARDI
──────────────────────────────
<MOTOR_ID>__<YYYYMMDD>__<LOKASYON_KODU>__<EKSEN>__<RUN_ID>.csv

Lokasyon kodları : BLOK_3YAK | BLOK_SOL | MNT_PLAT | DISLI_PER | DISLI_GOV | ALT
Eksenler         : X (shaft ekseni)  |  Y (silindir yönü)  |  Z (yanal)
Örnek            : ENG-042__20260318__DISLI_GOV__X__RUN-001.csv
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from enum import Enum


# ---------------------------------------------------------------------------
#  ENUM'LAR
# ---------------------------------------------------------------------------

class FaultCategory(Enum):
    COMBUSTION   = "Combustion"
    MECHANICAL   = "Mechanical"
    BEARING      = "Bearing"
    GEAR         = "Gear"
    IMBALANCE    = "Imbalance"
    MISALIGNMENT = "Misalignment"
    VALVE        = "Valve Train"
    STRUCTURAL   = "Structural Resonance"
    PROPELLER    = "Propeller"
    MOUNT        = "Engine Mount"


class Severity(Enum):
    INFO     = "Info"
    WARNING  = "Warning"
    CRITICAL = "Critical"


# ---------------------------------------------------------------------------
#  VERİ YAPILARI
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SensorChannel:
    """
    Bir ICP sensör kanalı = lokasyon + eksen.
    Her kanal için bağımsız referans ve analiz.
    """
    location_code: str       # Dosya adında kullanılan kısa kod
    location_name: str       # Okunabilir isim
    axis: str                # "X" | "Y" | "Z"
    description: str
    sensitive_to: List[FaultCategory] = field(default_factory=list)
    notes: str = ""

    @property
    def channel_key(self) -> str:
        return f"{self.location_code}_{self.axis}"


@dataclass(frozen=True)
class OrderDefinition:
    """Bir engine order'ının fiziksel anlamı."""
    order: float
    name: str
    source: str
    description: str
    fault_indicators: List[str]   = field(default_factory=list)
    category: FaultCategory       = FaultCategory.MECHANICAL
    # Hangi lokasyonlarda dominant görülür (boşsa hepsinde izlenir)
    dominant_locations: List[str] = field(default_factory=list)
    # Hangi eksende daha belirgin: "X" | "Y" | "Z" | "all"
    dominant_axis: str            = "all"
    # Order ekstraksiyonunda bu order'a özgü tolerans (±oran). None → analiz
    # motorunun varsayılan toleransı (genelde 5%) kullanılır.
    # Yan bantlar (28x, 28.41x, 29.59x, 30x) GMF'den (29x) ayrılabilmek için
    # daha sıkı tolerans gerektirir.
    tolerance_override: Optional[float] = None


@dataclass(frozen=True)
class FaultSignature:
    """Bir arızanın order örüntüsü."""
    name: str
    category: FaultCategory
    primary_orders: List[float]
    secondary_orders: List[float]
    description: str
    recommendation: str
    amplitude_ratio_threshold: float  = 1.5
    # Hangi lokasyonlarda aranmalı (boşsa hepsinde)
    relevant_locations: List[str]     = field(default_factory=list)
    dominant_axis: str                = "all"


@dataclass(frozen=True)
class FrequencyBand:
    name: str
    low_hz: float
    high_hz: float
    description: str


# ---------------------------------------------------------------------------
#  MOTOR PARAMETRELERİ
#  ⚠ Aşağıdaki değerler henüz teyit edilmemiştir — güncellenecek
# ---------------------------------------------------------------------------

ENGINE_CONFIG = {
    "name":               "4-Stroke 4-Cylinder Piston Aircraft Engine",
    "cylinders":          4,
    "strokes":            4,

    # TODO: Ateşleme sırasını teyit edin (Lycoming/Continental tipik: 1-3-4-2)
    "firing_order":       [1, 3, 4, 2],

    # Redüksiyon dişlisi
    "gear_ratio_reduction":   0.59,
    "gear_ratio_description": "Redüksiyon dişli: pervane mili = krank mili x 0.59",

    # Aksesuar dişli diş sayıları / devir oranları (KRANK MİLİ referansı ile)
    "accessory_gear_teeth": {
        # Yağ pompası: krank x 0.59 hızında döner, 2 dişlisi (her biri 7 dişli) içte meshlenir
        #   Krank-referanslı GMF = 7 × 0.59 = 4.13x
        "oil_pump_teeth":     7,
        "oil_pump_speed_ratio": 0.59,
        # Alternatör: krank x 5.9 hızında döner; kendi 1x orderı = 5.9x krank
        "alternator_speed_ratio": 5.9,
    },

    # Pervane bilgileri
    "propeller": {
        "blade_count":     3,       # 3 palli pervane
        "speed_ratio":     0.59,    # krank x 0.59 hızında döner
        "blade_pass_order": 1.77,   # 3 × 0.59 (krank referansı)
    },

    # Redüksiyon dişli kutusu (krank ↔ pervane)
    # CAD'den teyit edilen diş sayıları:
    #   Motor (pinyon) tarafı   : 29 diş   ← krank miline akuple
    #   Pervane (çark) tarafı   : 49 diş   ← pervane miline akuple
    #   Ara dişli (idler)       : 31 diş   ← motor-pervane arasında
    #   Governor dişlisi        : ayrı (henüz diş sayısı bilinmiyor)
    # GMF (krank ref):  ana mesh = 29 × krank = 29x
    "reduction_gearbox": {
        "type":              "parallel",
        "input_gear_teeth":  29,   # motor tarafı pinyon
        "output_gear_teeth": 49,   # pervane tarafı çark
        "idler_gear_teeth":  31,   # ara dişli
        "ratio":             0.59,
        "note": (
            "29x order ana mesh GMF'idir (krank ref). "
            "31 dişli ara dişlinin meshi 31x veya 29x'e yakın olabilir, "
            "ölçümde görülürse ayrıca tanımlanmalı."
        ),
    },

    # RPM bilgisi
    "nominal_rpm_range":  (1690, 3887),   # Krank mili RPM — teyit bekleniyor
    "max_rpm":            3887,
    "rpm_source":         "COMPUTED_FROM_ORDER",
    "rpm_source_warning": (
        "RPM tachometer YOKTUR. Yanma orderindan (2x) geri hesaplama yapilmaktadir. "
        "Sabit devir noktalarinda olcum alinmasi ve RPM manuel girilmesi onerilir."
    ),
    "recommended_rpm_points": [1690, 2000, 2300, 2500, 3887],
}


# ---------------------------------------------------------------------------
#  SENSÖR KANALLARI — 6 lokasyon × 3 eksen = 18 kanal
# ---------------------------------------------------------------------------

SENSOR_CHANNELS: List[SensorChannel] = [

    # ── Blok üzeri — 3. yatak yakını ──────────────────────────────────────
    SensorChannel(
        location_code="BLOK_3YAK", axis="X",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Krank milinin 3. yatağına yakın. X = shaft ekseni (eksenel/thrust yönü). "
                    "Eksenel yükleme, misalignment, krank thrust yatağı arızalarında yükselir.",
        sensitive_to=[FaultCategory.MISALIGNMENT, FaultCategory.BEARING, FaultCategory.STRUCTURAL],
        notes="Eksenel yön; krank thrust yatağı arızalarında ilk artış burada beklenir.",
    ),
    SensorChannel(
        location_code="BLOK_3YAK", axis="Y",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Y = silindir sırası yönü (dikey). Yanma basıncı ve piston kuvvetleri "
                    "bu yönde dominant. 0.5x, 2x, 4x orderları burada en belirgin.",
        sensitive_to=[FaultCategory.COMBUSTION, FaultCategory.MECHANICAL, FaultCategory.VALVE],
        notes="Yanma kaynaklı orderlar (0.5x, 2x, 4x, 6x) en güçlü bu kanalda görülür.",
    ),
    SensorChannel(
        location_code="BLOK_3YAK", axis="Z",
        location_name="Blok üzeri — 3. yatak yakını",
        description="Z = yanal eksen. Dengesizlik ve krank yanal yüklemesi.",
        sensitive_to=[FaultCategory.IMBALANCE, FaultCategory.BEARING],
    ),

    # ── Blok üzeri — sol mount yakını ─────────────────────────────────────
    SensorChannel(
        location_code="BLOK_SOL", axis="X",
        location_name="Blok üzeri — sol mount yakını",
        description="Sol motor montaj noktası yakını, eksenel yön. "
                    "Mount lastiği bozulmasında 1x ve 2x burada yükselir.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL, FaultCategory.MISALIGNMENT],
    ),
    SensorChannel(
        location_code="BLOK_SOL", axis="Y",
        location_name="Blok üzeri — sol mount yakını",
        description="Y = silindir yönü. Mount ile blok arasındaki titreşim iletimi.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.COMBUSTION],
    ),
    SensorChannel(
        location_code="BLOK_SOL", axis="Z",
        location_name="Blok üzeri — sol mount yakını",
        description="Z = yanal. Titreşim izolasyon kaybı.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.IMBALANCE],
    ),

    # ── Mount — platform tarafı ────────────────────────────────────────────
    SensorChannel(
        location_code="MNT_PLAT", axis="X",
        location_name="Mount — platform tarafı",
        description="Motor montaj platformu, eksenel yön. Motorden platforma geçen titreşimi ölçer. "
                    "Referans ile kıyaslamada mount izolasyon etkinliği değerlendirilebilir.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL],
        notes="Bu konumdaki genlikler blok sensörlerine göre belirgin şekilde düşük olmalı. "
              "Yüksekse mount degradasyonu düşünülmeli.",
    ),
    SensorChannel(
        location_code="MNT_PLAT", axis="Y",
        location_name="Mount — platform tarafı",
        description="Platform — dikey yön.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.STRUCTURAL],
    ),
    SensorChannel(
        location_code="MNT_PLAT", axis="Z",
        location_name="Mount — platform tarafı",
        description="Platform — yanal yön.",
        sensitive_to=[FaultCategory.MOUNT, FaultCategory.IMBALANCE],
    ),

    # ── Dişli kutusu — pervane yakını ─────────────────────────────────────
    SensorChannel(
        location_code="DISLI_PER", axis="X",
        location_name="Dişli kutusu — pervane yakını",
        description="Redüksiyon dişli kutusu pervane flanşı tarafı, eksenel. "
                    "Pervane dengesizliği eksenel yönde dominant. "
                    "Tüm orderlar krank mili referanslıdır (0.59 redüksiyon dahil).",
        sensitive_to=[FaultCategory.PROPELLER, FaultCategory.GEAR, FaultCategory.BEARING],
        notes="Pervane 1x = krank 0.59x frekansındadır ancak orderlar krank referanslı "
              "tanımlandığından analizde ek dönüşüm gerekmez.",
    ),
    SensorChannel(
        location_code="DISLI_PER", axis="Y",
        location_name="Dişli kutusu — pervane yakını",
        description="Dişli kutusu pervane tarafı — silindir yönü (dikey). "
                    "Dişli kutusu GMF orderları burada belirgin.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.PROPELLER],
    ),
    SensorChannel(
        location_code="DISLI_PER", axis="Z",
        location_name="Dişli kutusu — pervane yakını",
        description="Dişli kutusu pervane tarafı — yanal.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
    ),

    # ── Dişli kutusu — governor yakını ────────────────────────────────────
    SensorChannel(
        location_code="DISLI_GOV", axis="X",
        location_name="Dişli kutusu — governor yakını",
        description="Redüksiyon dişli kutusu governor tarafı, eksenel. "
                    "Ana mesh GMF (29x) ve governor sürücü dişlisi etkileri burada görülür.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
        notes="Governor sürücüsünün dişli sayısı bilinmediği için ayrı order tanımlanmadı. "
              "Bilgi edinildiğinde ORDER_DEFINITIONS'a eklenebilir.",
    ),
    SensorChannel(
        location_code="DISLI_GOV", axis="Y",
        location_name="Dişli kutusu — governor yakını",
        description="Dişli kutusu governor tarafı — dikey.",
        sensitive_to=[FaultCategory.GEAR],
    ),
    SensorChannel(
        location_code="DISLI_GOV", axis="Z",
        location_name="Dişli kutusu — governor yakını",
        description="Dişli kutusu governor tarafı — yanal.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
    ),

    # ── Alternatör üzeri ──────────────────────────────────────────────────
    SensorChannel(
        location_code="ALT", axis="X",
        location_name="Alternatör üzeri",
        description="Alternatör gövdesi, eksenel (shaft yönü). "
                    "Alternatör sürücü kayışı/dişlisi ve rotor dengesizliği.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.IMBALANCE, FaultCategory.BEARING],
        notes="Alternatör rotor frekansı = krank devri x sürücü çarpanı (3x). "
              "3x orderda artış alternatör kayış gerilmesi veya rotor dengesizliğine işaret eder.",
    ),
    SensorChannel(
        location_code="ALT", axis="Y",
        location_name="Alternatör üzeri",
        description="Alternatör — dikey yön.",
        sensitive_to=[FaultCategory.BEARING, FaultCategory.IMBALANCE],
    ),
    SensorChannel(
        location_code="ALT", axis="Z",
        location_name="Alternatör üzeri",
        description="Alternatör — yanal yön.",
        sensitive_to=[FaultCategory.BEARING],
    ),
]

# Hızlı erişim için sözlük: "BLOK_3YAK_X" -> SensorChannel
SENSOR_CHANNEL_MAP: Dict[str, SensorChannel] = {
    ch.channel_key: ch for ch in SENSOR_CHANNELS
}

# Lokasyon kodları listesi (UI için)
LOCATION_CODES: List[str] = list(dict.fromkeys(
    ch.location_code for ch in SENSOR_CHANNELS
))

# Lokasyon adları (UI için)
LOCATION_NAMES: Dict[str, str] = {
    ch.location_code: ch.location_name
    for ch in SENSOR_CHANNELS
}


# ---------------------------------------------------------------------------
#  ORDER TANIMLARI
#  Referans: KRANK MİLİ  (tüm sensörler için ortak)
#
#  4-strok 4-silindir motorun temel orderları:
#    0.5x = Yanma döngüsü fundamentali (4-strok: her 2 tur 1 yanma)
#    1x   = Krank mili dönme frekansı (dengesizlik)
#    2x   = Ateşleme frekansı (4-sil. 4-strok: 2 güç stroğu/tur)
#    4x   = 2. ateşleme harmoniği
#    Nx   = Dişli diş sayısı x krank frekansı
# ---------------------------------------------------------------------------

ORDER_DEFINITIONS: Dict[float, OrderDefinition] = {

    0.5: OrderDefinition(
        order=0.5,
        name="0.5x (Yarım Order)",
        source="Yanma Döngüsü Fundamentali",
        description=(
            "4-strok motorun temel frekansı — her 2 krank turunda 1 yanma döngüsü. "
            "Normal çalışmada düşük genlikli olmalı. Artış misfire veya yanma "
            "düzensizliğine işaret eder."
        ),
        fault_indicators=["Ateşleme arızası (misfire)", "Düzensiz yanma", "Ateşleme zamanlaması hatası"],
        category=FaultCategory.COMBUSTION,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    0.59: OrderDefinition(
        order=0.59,
        name="0.59x (Pervane 1x)",
        source="Pervane Mili Dönme Frekansı",
        description=(
            "Pervane milinin temel dönme frekansı (krank × 0.59 redüksiyon). "
            "Pervane kütle dengesizliği, kanat hasarı, hub çarpıklığı veya "
            "pitch farklılığında bu order yükselir. Krank 1x (1.0x) ile karıştırılmamalı."
        ),
        fault_indicators=[
            "Pervane kütle dengesizliği",
            "Pervane kanat hasarı (çentik, erozyon)",
            "Pervane hub çarpıklığı",
            "Kanatlar arası pitch farklılığı",
        ],
        category=FaultCategory.PROPELLER,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="Z",
    ),

    1.0: OrderDefinition(
        order=1.0,
        name="1x (Krank Dönme Frekansı)",
        source="Krank Mili Rotasyonu",
        description=(
            "Krank milinin temel dönme frekansı. Krank tarafı kütle dengesizliğinin "
            "birincil göstergesi (eğilmiş krank, sürücü taraf kavrama dengesizliği). "
            "Pervane dengesizliği 1x'te DEĞİL, 0.59x'te yükselir."
        ),
        fault_indicators=[
            "Krank mili kütle dengesizliği",
            "Büküleşmiş krank mili",
            "Krank sürücü taraf bağlantı çarpıklığı",
        ],
        category=FaultCategory.IMBALANCE,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Z",
    ),

    1.5: OrderDefinition(
        order=1.5,
        name="1.5x",
        source="Yanma + Rotasyon Etkileşimi",
        description=(
            "Yarım order ve birinci order arasındaki intermodülasyon. "
            "Silindir-silindir yanma varyasyonu veya kombine dengesizlik + yanma sorununda görülür."
        ),
        fault_indicators=["Silindir-silindir yanma farkı", "Kombine dengesizlik+yanma"],
        category=FaultCategory.COMBUSTION,
        dominant_axis="Y",
    ),

    1.77: OrderDefinition(
        order=1.77,
        name="1.77x (Pervane Blade-Pass)",
        source="Pervane Kanat Geçiş Frekansı",
        description=(
            "Pervane kanat-geçiş (blade-pass) frekansı: 3 kanat × 0.59 (pervane devir oranı) = 1.77x krank. "
            "Aerodinamik kaynaklı pervane etkisi bu orderda belirgindir. "
            "Kanatlar arasındaki açı (pitch) farklılığı, kanat erozyonu/hasarı "
            "veya boşa dönen hava akışı varyasyonu bu orderı yükseltir."
        ),
        fault_indicators=[
            "Kanatlar arası pitch farklılığı",
            "Pervane kanat erozyonu / çentik",
            "Aerodinamik dengesizlik",
            "Spinner çarpıklığı",
        ],
        category=FaultCategory.PROPELLER,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="all",
    ),

    2.0: OrderDefinition(
        order=2.0,
        name="2x (Ateşleme Frekansı)",
        source="Ateşleme Frekansı",
        description=(
            "4-silindirli 4-strok motorun birincil ateşleme frekansı "
            "(tur başına 2 güç stroğu). RPM'in yanma orderından geri hesaplandığı "
            "bu projede 2x genliği RPM hesaplamasında referans alınmaktadır. "
            "Aşırı artış yanma basıncı varyasyonu veya ikincil dengesizliğe işaret eder."
        ),
        fault_indicators=[
            "Yanma basıncı varyasyonu",
            "İkincil dengesizlik (piston kuvvetleri)",
            "Piston yanal kuvveti",
        ],
        category=FaultCategory.COMBUSTION,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    3.0: OrderDefinition(
        order=3.0,
        name="3x (Yapısal / Torsiyonel)",
        source="Krank Torsiyonel / Yapısal Rezonans",
        description=(
            "Krank mili torsiyonel rezonansı veya yapısal rezonans harmoniği. "
            "Belirli RPM aralığında pik yapması torsiyonel rezonansa işaret eder."
        ),
        fault_indicators=["Krank torsiyonel rezonansı", "Yapısal rezonans"],
        category=FaultCategory.STRUCTURAL,
    ),

    4.0: OrderDefinition(
        order=4.0,
        name="4x (2. Ateşleme Harmoniği)",
        source="Ateşleme Frekansı 2. Harmoniği",
        description=(
            "Ateşleme frekansının 2. harmoniği; aynı zamanda tur başına 4 piston stroğu. "
            "Valf treni sorunları, piston-silindir etkileşimi. "
            "UYARI: 4.13x (yağ pompası GMF) bu order'a çok yakındır (%3.25); "
            "ölçüm çözünürlüğüne göre ayırt etmek zor olabilir."
        ),
        fault_indicators=["Valf treni sorunu", "Piston-silindir etkileşimi", "Yanma harmoniği"],
        category=FaultCategory.VALVE,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    4.13: OrderDefinition(
        order=4.13,
        name="4.13x (Yağ Pompası GMF)",
        source="Yağ Pompası Sürücü Dişlisi",
        description=(
            "Yağ pompası dişli geçiş frekansı: 7 diş × 0.59 (pompa devir oranı) = 4.13x krank. "
            "Yağ pompası kendi içinde 7 dişli iki dişli meshlemesine sahiptir; bu order "
            "diş aşınması, basınç pulsasyonu veya kavitasyona işaret eder. "
            "UYARI: 4x (ateşleme 2. harmoniği) ile spektral olarak çok yakındır."
        ),
        fault_indicators=["Yağ pompası dişli aşınması", "Yağ pompası kavitasyonu", "Basınç pulsasyonu"],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        tolerance_override=0.015,   # 4x ile ayrılabilsin
    ),

    6.0: OrderDefinition(
        order=6.0,
        name="6x (Valf Treni)",
        source="Valf Treni",
        description=(
            "4-silindirli 4-strok motorda valf olayları frekansı. "
            "Yorulmuş valf yayı, aşınmış rocker arm veya kam lobunda aşınma."
        ),
        fault_indicators=["Valf yayı yorulması", "Rocker arm aşınması", "Kam lobu aşınması"],
        category=FaultCategory.VALVE,
        dominant_axis="Y",
    ),

    8.0: OrderDefinition(
        order=8.0,
        name="8x (4. Ateşleme Harmoniği)",
        source="Ateşleme 4. Harmoniği / Piston",
        description="Piston vuruşu (piston slap) ve silindir iç yüzey etkileşimleri.",
        fault_indicators=["Piston vuruşu (slap)", "Segment aşınması", "Silindir yuvarlaksal bozulma"],
        category=FaultCategory.MECHANICAL,
        dominant_axis="Y",
    ),

    5.9: OrderDefinition(
        order=5.9,
        name="5.9x (Alternatör 1x)",
        source="Alternatör Rotor Frekansı",
        description=(
            "Alternatör rotorunun temel dönme frekansı (krank × 5.9). "
            "Rotor kütle dengesizliği, kayış/kaplinde gevşeklik, alternatör yatak aşınması "
            "bu orderı yükseltir. UYARI: 6x (valf treni) ile spektral olarak yakındır "
            "(%1.7), ölçüm çözünürlüğüne göre ayırt etmek zor olabilir; birlikte değerlendirin."
        ),
        fault_indicators=[
            "Alternatör rotor dengesizliği",
            "Alternatör yatak aşınması",
            "Kayış/kaplin gevşekliği",
        ],
        category=FaultCategory.IMBALANCE,
        dominant_locations=["ALT"],
        dominant_axis="all",
        tolerance_override=0.008,   # 6x ile ayrılabilsin
    ),

    # ── Dişli kutusu yan bantları (GMF=29x etrafında) ────────────────────────
    # Yan bant aralığı, hangi dişlinin hasarlı olduğunu söyler:
    #   ±1x   (28x, 30x)     → pinyon (29-dişli, krank tarafı) tarafında hasar
    #   ±0.59x (28.41, 29.59)→ çark (49-dişli, pervane tarafı) tarafında hasar
    28.0: OrderDefinition(
        order=28.0,
        name="28x (GMF − 1x Pinyon Yan Bandı)",
        source="Dişli Kutusu Pinyon Tarafı Modülasyonu",
        description=(
            "29x GMF − 1x (krank/pinyon mili frekansı) alt yan bandı. "
            "Bu orderın 30x ile birlikte yükselmesi pinyon (29-dişli, motor tarafı) "
            "üzerinde lokal bir hasar (kırık diş, çatlak, çukurlaşma) işaretidir."
        ),
        fault_indicators=["Pinyon dişlisi lokal hasarı", "Pinyon diş çatlağı / çukurlaşması"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.012,   # 29x'ten ayrılabilsin
    ),

    28.41: OrderDefinition(
        order=28.41,
        name="28.41x (GMF − 0.59x Çark Yan Bandı)",
        source="Dişli Kutusu Çark Tarafı Modülasyonu",
        description=(
            "29x GMF − 0.59x (pervane/çark mili frekansı) alt yan bandı. "
            "Bu orderın 29.59x ile birlikte yükselmesi çark (49-dişli, pervane tarafı) "
            "üzerinde lokal bir hasar işaretidir."
        ),
        fault_indicators=["Çark dişlisi lokal hasarı", "Çark diş kırılması / çukurlaşma"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.008,   # 28x ve 29x'ten ayrılabilsin
    ),

    29.0: OrderDefinition(
        order=29.0,
        name="29x (Dişli Kutusu GMF)",
        source="Redüksiyon Dişli Kutusu Ana Mesh (Pinyon × Çark)",
        description=(
            "Redüksiyon dişli kutusunun ana dişli ağzı geçiş frekansı. "
            "CAD'den teyit: motor tarafı 29 dişli pinyon × pervane tarafı 49 dişli çark; "
            "her iki dişli için aynı GMF = 29 × krank = 49 × 0.59 × krank ≈ 29x. "
            "TANI İPUCU: 29x etrafındaki yan bantların aralığı hangi dişlinin hasarlı "
            "olduğunu söyler — ±1x bantları (28x, 30x) pinyon, ±0.59x bantları "
            "(28.41x, 29.59x) çark tarafı hasarına işaret eder."
        ),
        fault_indicators=[
            "Dişli kutusu pinyon/çark aşınması",
            "Dişli yüzeyi çukurlaşması/soyulması (pitting/spalling)",
            "Dişli yatakları aşınması",
            "Dişli boşluğu (backlash) artışı",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV", "BLOK_3YAK"],
        dominant_axis="all",
    ),

    29.59: OrderDefinition(
        order=29.59,
        name="29.59x (GMF + 0.59x Çark Yan Bandı)",
        source="Dişli Kutusu Çark Tarafı Modülasyonu",
        description=(
            "29x GMF + 0.59x (pervane/çark mili frekansı) üst yan bandı. "
            "28.41x ile simetrik artış çark (49-dişli) tarafında hasar göstergesidir."
        ),
        fault_indicators=["Çark dişlisi lokal hasarı"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.008,
    ),

    30.0: OrderDefinition(
        order=30.0,
        name="30x (GMF + 1x Pinyon Yan Bandı)",
        source="Dişli Kutusu Pinyon Tarafı Modülasyonu",
        description=(
            "29x GMF + 1x (krank/pinyon mili frekansı) üst yan bandı. "
            "28x ile simetrik artış pinyon (29-dişli) tarafında hasar göstergesidir."
        ),
        fault_indicators=["Pinyon dişlisi lokal hasarı"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
        tolerance_override=0.012,
    ),

    58.0: OrderDefinition(
        order=58.0,
        name="58x (Dişli Kutusu GMF 2. Harmoniği)",
        source="Dişli Kutusu Ana Mesh GMF 2. Harmoniği",
        description=(
            "Dişli kutusu ana mesh GMF'inin 2. harmoniği (2 × 29x). "
            "29x ile birlikte yükseliyorsa dişli aşınması ilerliyor demektir."
        ),
        fault_indicators=["İleri düzey dişli aşınması", "Diş profili hasarı"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV", "BLOK_3YAK"],
    ),

    87.0: OrderDefinition(
        order=87.0,
        name="87x (Dişli Kutusu GMF 3. Harmoniği)",
        source="Dişli Kutusu Ana Mesh GMF 3. Harmoniği",
        description="Dişli kutusu GMF 3. harmoniği (3 × 29x). Ciddi dişli hasarı göstergesi.",
        fault_indicators=["Ağır dişli hasarı", "Diş soyulması (spalling)"],
        category=FaultCategory.GEAR,
        dominant_locations=["DISLI_PER", "DISLI_GOV"],
    ),
}


# ---------------------------------------------------------------------------
#  ARIZA İMZALARI
# ---------------------------------------------------------------------------

FAULT_SIGNATURES: List[FaultSignature] = [

    FaultSignature(
        name="Krank Mili Kütle Dengesizliği",
        category=FaultCategory.IMBALANCE,
        primary_orders=[1.0],
        secondary_orders=[2.0],
        description=(
            "Dominant 1x order krank tarafı kütle dengesizliğini gösterir. "
            "Eğilmiş krank mili veya krank sürücü taraf bağlantı çarpıklığında görülür. "
            "Pervane dengesizliği bu signatür DEĞİL — pervane için 0.59x'e bakılır."
        ),
        recommendation=(
            "Krank milinde hasar veya eğrilik kontrol edin. "
            "Krank sürücü taraf bağlantı düzgünlüğünü kontrol edin. "
            "Blok sensörlerinde (BLOK_3YAK, BLOK_SOL) Z-eksenine odaklanın."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Z",
    ),

    FaultSignature(
        name="Pervane Dengesizliği / Kanat Anomalisi",
        category=FaultCategory.PROPELLER,
        primary_orders=[0.59, 1.77],
        secondary_orders=[1.18],
        description=(
            "0.59x (pervane 1x) artışı pervane kütle dengesizliğine işaret eder "
            "(hub çarpıklığı, kanat hasarı, montaj problemi). "
            "1.77x (blade-pass = 3 kanat × 0.59) artışı ise kanatlar arası pitch "
            "farklılığı, kanat erozyonu veya aerodinamik dengesizliği gösterir."
        ),
        recommendation=(
            "Pervane kanat profillerini çentik ve erozyon açısından inceleyin. "
            "Pervane balansını ve kanat açı (pitch) tutarlılığını kontrol edin. "
            "Hub ve spinner üzerinde çatlak kontrolü yapın. "
            "Dişli kutusu pervane tarafı (DISLI_PER) sensörüne odaklanın."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
        dominant_axis="all",
    ),

    FaultSignature(
        name="Mil Hizasızlığı (Misalignment)",
        category=FaultCategory.MISALIGNMENT,
        primary_orders=[1.0, 2.0],
        secondary_orders=[3.0],
        description=(
            "Yüksek 1x ve 2x order eksenel bileşenlerle birlikte angular veya "
            "paralel hizasızlığa işaret eder."
        ),
        recommendation=(
            "Motor montaj hizasını kontrol edin. Krank mili eksenel boşluğunu ölçün. "
            "Pervane flanşı çarpıklığını kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        dominant_axis="X",
    ),

    FaultSignature(
        name="Yanma Anomalisi / Ateşleme Arızası",
        category=FaultCategory.COMBUSTION,
        primary_orders=[0.5, 2.0],
        secondary_orders=[1.5, 4.0],
        description=(
            "0.5x (yarım order) artışı 4-strok motorun en önemli yanma göstergesidir. "
            "Normal çalışmada düşük olmalıdır; artış misfire veya düzensiz yanmayı gösterir."
        ),
        recommendation=(
            "Bujileri kontrol edin ve gerekirse değiştirin. Magneto zamanlamasını kontrol edin. "
            "Yakıt enjektör debilerini dengeleyin. Her silindirde kompresyon testi yapın."
        ),
        amplitude_ratio_threshold=1.6,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Valf Treni Aşınması",
        category=FaultCategory.VALVE,
        primary_orders=[4.0, 6.0],
        secondary_orders=[8.0],
        description=(
            "4x ve 6x order artışı aşınmış rocker arm, zayıf valf yayı veya "
            "kam lobu aşınmasına işaret eder."
        ),
        recommendation=(
            "Rocker arm boşluklarını ölçün. Valf yayı kuvvetlerini kontrol edin. "
            "Kam lobu profillerini inceleyin."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Dişli Kutusu Genel Aşınma (Pinyon × Çark Mesh)",
        category=FaultCategory.GEAR,
        primary_orders=[29.0],
        secondary_orders=[58.0, 87.0],
        description=(
            "29x order artışı redüksiyon dişli kutusunun ana mesh'inde (29 dişli pinyon × "
            "49 dişli çark) genel aşınmaya işaret eder. 58x ve 87x harmonikleri eklendiğinde "
            "hasar ilerliyor demektir. Hangi dişlide olduğunu daraltmak için yan bant "
            "imzalarına bakın (pinyon: ±1x, çark: ±0.59x)."
        ),
        recommendation=(
            "Dişli kutusu kapağını açıp pinyon ve çark dişlerini çukurlaşma (pitting), "
            "soyulma (spalling) ve boşluk (backlash) açısından inceleyin. "
            "Dişli yatak boşluklarını ölçün. Yağ filtresinde metal partikül analizi yapın."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["DISLI_PER", "DISLI_GOV", "BLOK_3YAK"],
    ),

    FaultSignature(
        name="Dişli Kutusu Pinyon (29-Dişli, Motor Tarafı) Lokal Hasarı",
        category=FaultCategory.GEAR,
        primary_orders=[28.0, 30.0],
        secondary_orders=[29.0],
        description=(
            "29x GMF etrafında ±1x (krank/pinyon mili frekansı) aralıklı yan bantlar "
            "(28x ve 30x) pinyon dişlisi üzerinde lokal bir kusura işaret eder — "
            "tek bir kırık/çatlak diş, çukurlaşma veya pitting. "
            "Yan bant aralığı = hasarlı dişlinin dönüş frekansı."
        ),
        recommendation=(
            "Krank tarafı 29-dişli pinyonu, dişleri tek tek inceleyin. "
            "Kırık veya hasarlı diş ararken büyüteç ve fluoresan boya kullanın. "
            "Pinyon mili yatak boşluğunu da ölçün."
        ),
        amplitude_ratio_threshold=1.3,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
    ),

    FaultSignature(
        name="Dişli Kutusu Çark (49-Dişli, Pervane Tarafı) Lokal Hasarı",
        category=FaultCategory.GEAR,
        primary_orders=[28.41, 29.59],
        secondary_orders=[29.0],
        description=(
            "29x GMF etrafında ±0.59x (pervane/çark mili frekansı) aralıklı yan bantlar "
            "(28.41x ve 29.59x) çark dişlisi üzerinde lokal bir kusura işaret eder. "
            "Yan bant aralığı = hasarlı dişlinin dönüş frekansı (= 0.59x krank)."
        ),
        recommendation=(
            "Pervane tarafı 49-dişli çarkı, dişleri tek tek inceleyin. "
            "Pervane mili yatak boşluğunu ölçün. "
            "Pinyon dişlerini de kontrol edin (hasarın yayılmadığından emin olmak için)."
        ),
        amplitude_ratio_threshold=1.3,
        relevant_locations=["DISLI_PER", "DISLI_GOV"],
    ),

    FaultSignature(
        name="Alternatör Rotor Dengesizliği / Yatak Aşınması",
        category=FaultCategory.IMBALANCE,
        primary_orders=[5.9],
        secondary_orders=[11.8],
        description=(
            "5.9x order (alternatör 1x = krank × 5.9) artışı alternatör rotorunda "
            "kütle dengesizliğine veya rotor yataklarında aşınmaya işaret eder. "
            "11.8x harmoniğinin eklenmesi yatak problemini öne çıkarır."
        ),
        recommendation=(
            "Alternatör kayış gerilmesini kontrol edin. "
            "Rotor yataklarında oynaklık testi yapın (Manuel kontrol veya endoskop). "
            "Gerekirse alternatörü söküp dengeleyin veya yatak değiştirin."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["ALT"],
    ),

    FaultSignature(
        name="Yağ Pompası Dişli Aşınması",
        category=FaultCategory.GEAR,
        primary_orders=[4.13],
        secondary_orders=[8.26],
        description=(
            "4.13x order (7 diş × 0.59 pompa devir oranı) artışı yağ pompası dişli ağzı "
            "anomalisine işaret eder. UYARI: 4x (ateşleme harmoniği) ile spektral olarak "
            "çok yakındır; her iki order'ı birlikte değerlendirin."
        ),
        recommendation=(
            "Yağ pompası dişli durumunu ve gövde boşluklarını kontrol edin. "
            "Farklı devir noktalarında yağ basıncını ölçün. "
            "Yağ filtresinde metal partikül analizi yapın."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
    ),

    FaultSignature(
        name="Piston Vuruşu / Segment Aşınması",
        category=FaultCategory.MECHANICAL,
        primary_orders=[8.0],
        secondary_orders=[4.0, 16.0],
        description=(
            "8x order artışı ve geniş bantlı gürültü artışı piston-silindir boşluğu "
            "sorununa işaret eder."
        ),
        recommendation=(
            "Tüm silindirlerde kompresyon ve diferansiyel basınç testi yapın. "
            "Silindir içini borescope ile inceleyin."
        ),
        amplitude_ratio_threshold=1.6,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    FaultSignature(
        name="Motor Montaj (Mount) Bozulması",
        category=FaultCategory.MOUNT,
        primary_orders=[1.0, 2.0],
        secondary_orders=[0.5],
        description=(
            "Düşük frekanslarda geniş bant artışı ve mount sensöründe (MNT_PLAT) "
            "yüksek genlik, montaj lastiğinin bozulduğuna işaret eder."
        ),
        recommendation=(
            "Tüm motor montaj burçlarını çatlak, sertleşme ve çökme açısından inceleyin. "
            "Montaj cıvata tork değerlerini kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["MNT_PLAT", "BLOK_SOL"],
    ),

    FaultSignature(
        name="Krank Mili Torsiyonel Rezonansı",
        category=FaultCategory.STRUCTURAL,
        primary_orders=[3.0, 6.0],
        secondary_orders=[1.5],
        description=(
            "Belirli RPM noktalarında 3x ve 6x order kilitli rezonans krank mili "
            "torsiyonel titreşimine işaret eder."
        ),
        recommendation=(
            "Vibrasyon vs RPM haritasını inceleyerek rezonans noktalarını belirleyin. "
            "Krank milini, pervane vantuzunu ve dinamik sönümleyiciyi (varsa) kontrol edin."
        ),
        amplitude_ratio_threshold=1.7,
    ),
]


# ---------------------------------------------------------------------------
#  FREKANS BANTLARI  (mutlak Hz — sabit devir veya referans analizi için)
# ---------------------------------------------------------------------------

FREQUENCY_BANDS: List[FrequencyBand] = [
    FrequencyBand("Alt-senkron",         0.0,    25.0,
                  "Mil frekansı altı — yapısal, instabilite"),
    FrequencyBand("Mil Fundamentali",   25.0,    55.0,
                  "Krank mili dönme aralığı (1800-2700 RPM)"),
    FrequencyBand("Ateşleme Frekansı",  55.0,   110.0,
                  "Yanma / ateşleme harmonikleri"),
    FrequencyBand("Valf Treni",        100.0,   250.0,
                  "Valf treni ve kam mili aktivitesi"),
    FrequencyBand("Dişli Ağzı Düşük",  250.0,   800.0,
                  "Düşük dişli ağzı frekansları (yağ pompası 4.13x, alternatör 5.9x)"),
    FrequencyBand("Dişli Ağzı Yüksek", 800.0,  2500.0,
                  "Yüksek dişli ağzı frekansları (dişli kutusu 29x ≈ 800-1900 Hz @ 1700-3900 RPM)"),
    FrequencyBand("Yüksek Frekans",   2500.0, 10000.0,
                  "Yapısal rezonanslar, yatak arıza frekansları"),
]


# ---------------------------------------------------------------------------
#  UYARI EŞİKLERİ  (referansa göre genlik oranı)
# ---------------------------------------------------------------------------

ALERT_THRESHOLDS = {
    Severity.WARNING:  1.5,   # Referansın %50 üzeri
    Severity.CRITICAL: 2.5,   # Referansın %150 üzeri
}

# Her zaman izlenecek orderlar
MANDATORY_MONITOR_ORDERS = [0.5, 0.59, 1.0, 1.77, 2.0, 4.0, 4.13, 5.9, 29.0]

# Hassas orderlar — daha düşük eşik uygulanır
SENSITIVE_ORDERS               = [0.59, 1.77, 4.13, 5.9, 28.0, 28.41, 29.0, 29.59, 30.0, 58.0, 87.0]
SENSITIVE_THRESHOLD_MULTIPLIER = 0.8   # Normal eşiğin %80'i
