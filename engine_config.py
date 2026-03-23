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

    # Aksesuar dişli diş sayıları (KRANK MİLİ referansı ile)
    # TODO: Tüm diş sayılarını motor dokümantasyonundan teyit edin
    "accessory_gear_teeth": {
        "magneto_drive":      29,   # 29x order -> magneto GMF  [TEYIT EDİLDİ]
        "camshaft_drive":     22,   # 22x order -> kam mili GMF [teyit bekleniyor]
        "oil_pump_drive":     14,   # 14x order [teyit bekleniyor]
        "vacuum_pump_drive":  12,   # 12x order [teyit bekleniyor]
        "alternator_drive":    3,   # Alternatör çarpanı [teyit bekleniyor]
    },

    # Redüksiyon dişli kutusu iç dişli sayıları
    # TODO: Motor dokümantasyonundan doldurulacak
    "reduction_gearbox": {
        "type":              "TODO",   # "planetary" veya "parallel"
        "input_gear_teeth":  None,
        "output_gear_teeth": None,
        "note": (
            "Diş sayıları bilinirse dişli kutusu GMF orderları "
            "ORDER_DEFINITIONS'a eklenebilir. "
            "Planetary ise: GMF = N_planet x shaft_freq"
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
                    "Governor sürücü dişlisi GMF'i burada görülür.",
        sensitive_to=[FaultCategory.GEAR, FaultCategory.BEARING],
        notes="Governor sürücüsünün kendi dişli sayısı bilinirse ORDER_DEFINITIONS'a ekleyin.",
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

    1.0: OrderDefinition(
        order=1.0,
        name="1x (Krank Dönme Frekansı)",
        source="Krank Mili Rotasyonu",
        description=(
            "Krank milinin temel dönme frekansı. Kütle dengesizliğinin birincil "
            "göstergesi. Pervane dengesizliği, büküleşmiş krank veya bozulmuş "
            "pervane flanşında dominant olarak yükselir."
        ),
        fault_indicators=[
            "Kütle dengesizliği (pervane/krank)",
            "Pervane kanat hasarı",
            "Büküleşmiş krank mili",
            "Pervane flanşı çarpıklığı",
        ],
        category=FaultCategory.IMBALANCE,
        dominant_locations=["DISLI_PER", "DISLI_GOV", "BLOK_3YAK"],
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
        name="3x",
        source="Alternatör / Yapısal",
        description=(
            "Alternatör sürücü çarpanı (3x). Aynı zamanda krank torsiyonel "
            "rezonansı veya yapısal rezonans harmoniği olabilir."
        ),
        fault_indicators=[
            "Alternatör kayış gerilmesi / sürücü dişli aşınması",
            "Krank torsiyonel rezonansı",
            "Yapısal rezonans",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["ALT"],
        dominant_axis="X",
    ),

    4.0: OrderDefinition(
        order=4.0,
        name="4x (2. Ateşleme Harmoniği)",
        source="Ateşleme Frekansı 2. Harmoniği",
        description=(
            "Ateşleme frekansının 2. harmoniği; aynı zamanda tur başına 4 piston stroğu. "
            "Valf treni sorunları, piston-silindir etkileşimi."
        ),
        fault_indicators=["Valf treni sorunu", "Piston-silindir etkileşimi", "Yanma harmoniği"],
        category=FaultCategory.VALVE,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
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

    12.0: OrderDefinition(
        order=12.0,
        name="12x (Vakum Pompası Dişli GMF)",
        source="Vakum Pompası Sürücü Dişlisi",
        description=(
            "Vakum pompası sürücü dişlisi diş geçiş frekansı (12 diş x krank frekansı). "
            "TODO: Diş sayısı teyit edilmemiştir."
        ),
        fault_indicators=["Vakum pompası dişli aşınması", "Sürücü bağlantı aşınması"],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
    ),

    14.0: OrderDefinition(
        order=14.0,
        name="14x (Yağ Pompası Dişli GMF)",
        source="Yağ Pompası Sürücü Dişlisi",
        description=(
            "Yağ pompası sürücü dişlisi diş geçiş frekansı (14 diş x krank frekansı). "
            "TODO: Diş sayısı teyit edilmemiştir."
        ),
        fault_indicators=["Yağ pompası dişli aşınması", "Yağ pompası kavitasyonu", "Basınç pulsasyonu"],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
    ),

    22.0: OrderDefinition(
        order=22.0,
        name="22x (Kam Mili Dişli GMF)",
        source="Kam Mili Sürücü Dişlisi",
        description=(
            "Kam mili sürücü dişlisi diş geçiş frekansı (22 diş x krank frekansı). "
            "Kam mili krank milinin yarısı hızında döndüğünden kam tarafında "
            "gerçek GMF = 22 x 0.5 = 11x olur, ancak krank referanslı ölçümde 22x görülür. "
            "TODO: Diş sayısı teyit edilmemiştir."
        ),
        fault_indicators=["Kam mili dişli aşınması", "Zamanlama dişli boşluğu artışı", "Dişli yüzeyi çukurlaşması"],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL"],
        dominant_axis="Y",
    ),

    29.0: OrderDefinition(
        order=29.0,
        name="29x (Magneto Sürücü Dişli GMF)",
        source="Magneto Sürücü Dişlisi",
        description=(
            "Magneto sürücü dişlisi diş geçiş frekansı (29 diş x krank frekansı). "
            "TEYIT EDİLMİŞ: Bu motor 29 dişli magneto sürücüsü kullanmaktadır. "
            "Hem blok sensörlerinde hem dişli kutusu sensörlerinde görülebilir."
        ),
        fault_indicators=[
            "Magneto sürücü dişli aşınması",
            "Dişli yüzeyi çukurlaşması/soyulması (pitting/spalling)",
            "Magneto mili yatağı aşınması",
            "Sürücü dişli boşluğu artışı",
        ],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL", "DISLI_GOV"],
        dominant_axis="all",
    ),

    44.0: OrderDefinition(
        order=44.0,
        name="44x (Kam Mili 2x GMF)",
        source="Kam Mili Dişli GMF 2. Harmoniği",
        description="Kam mili sürücü dişlisi GMF'inin 2. harmoniği (2 x 22x).",
        fault_indicators=["İleri düzey kam mili dişli aşınması"],
        category=FaultCategory.GEAR,
    ),

    58.0: OrderDefinition(
        order=58.0,
        name="58x (Magneto GMF 2. Harmoniği)",
        source="Magneto Sürücü Dişli GMF 2. Harmoniği",
        description=(
            "Magneto sürücü dişlisi GMF'inin 2. harmoniği (2 x 29x). "
            "29x ile birlikte yükseliyorsa dişli aşınması ilerliyor demektir."
        ),
        fault_indicators=["İleri düzey magneto dişli aşınması", "Diş profili hasarı"],
        category=FaultCategory.GEAR,
        dominant_locations=["BLOK_3YAK", "BLOK_SOL", "DISLI_GOV"],
    ),

    87.0: OrderDefinition(
        order=87.0,
        name="87x (Magneto GMF 3. Harmoniği)",
        source="Magneto Sürücü Dişli GMF 3. Harmoniği",
        description="Magneto GMF 3. harmoniği (3 x 29x). Ciddi dişli hasarı göstergesi.",
        fault_indicators=["Ağır magneto dişli hasarı", "Diş soyulması (spalling)"],
        category=FaultCategory.GEAR,
    ),
}


# ---------------------------------------------------------------------------
#  ARIZA İMZALARI
# ---------------------------------------------------------------------------

FAULT_SIGNATURES: List[FaultSignature] = [

    FaultSignature(
        name="Pervane / Krank Kütle Dengesizliği",
        category=FaultCategory.IMBALANCE,
        primary_orders=[1.0],
        secondary_orders=[2.0],
        description=(
            "Dominant 1x order kütle dengesizliğini gösterir. "
            "Pervane hasarı (kuş çarpması, çentik), krank mili eğriliği veya "
            "pervane flanşı çarpıklığında görülür."
        ),
        recommendation=(
            "Pervane montajını dengeleyin. Krank milinde hasar veya eğrilik kontrol edin. "
            "Pervane göbeğinde çatlak kontrolü yapın. "
            "Dişli kutusu pervane tarafı (DISLI_PER) sensörüne odaklanın."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["DISLI_PER", "DISLI_GOV", "BLOK_3YAK"],
        dominant_axis="Z",
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
        name="Magneto Sürücü Dişli Aşınması",
        category=FaultCategory.GEAR,
        primary_orders=[29.0],
        secondary_orders=[58.0, 87.0],
        description=(
            "29x order artışı magneto sürücü dişlisinin aşındığını gösterir. "
            "58x ve 87x harmoniklerinin eklenmesi hasarın ilerlediğini gösterir. "
            "Bu motor 29 dişli magneto sürücüsü kullanmaktadır (teyit edildi)."
        ),
        recommendation=(
            "Magneto sürücü dişlisini çukurlaşma, soyulma ve boşluk açısından inceleyin. "
            "Aşınma tespit edilirse sürücü dişlisini ve magneto yatağını değiştirin. "
            "Değişimden sonra magneto zamanlamasını kontrol edin."
        ),
        amplitude_ratio_threshold=1.4,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL", "DISLI_GOV"],
    ),

    FaultSignature(
        name="Kam Mili Dişli Aşınması",
        category=FaultCategory.GEAR,
        primary_orders=[22.0],
        secondary_orders=[44.0],
        description="22x order artışı kam mili sürücü dişlisi aşınmasına veya boşluk artışına işaret eder.",
        recommendation=(
            "Kam mili sürücü dişli ağzını inceleyin. Dişli boşluğu ve diş yüzeylerini kontrol edin. "
            "Kam zamanlamasının doğruluğunu ölçün."
        ),
        amplitude_ratio_threshold=1.5,
        relevant_locations=["BLOK_3YAK", "BLOK_SOL"],
    ),

    FaultSignature(
        name="Yağ Pompası Dişli Aşınması",
        category=FaultCategory.GEAR,
        primary_orders=[14.0],
        secondary_orders=[28.0],
        description="14x order artışı yağ pompası dişli ağzı anomalisine işaret eder.",
        recommendation=(
            "Yağ pompası dişli durumunu ve gövde boşluklarını kontrol edin. "
            "Farklı devir noktalarında yağ basıncını ölçün."
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
                  "Düşük dişli ağzı frekansları (yağ pompası, kam mili)"),
    FrequencyBand("Dişli Ağzı Yüksek", 800.0,  2500.0,
                  "Yüksek dişli ağzı frekansları (magneto: ~800-1300 Hz @ 1800-2700 RPM)"),
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
MANDATORY_MONITOR_ORDERS = [0.5, 1.0, 2.0, 4.0, 29.0]

# Hassas orderlar — daha düşük eşik uygulanır
SENSITIVE_ORDERS               = [29.0, 58.0, 87.0, 22.0]
SENSITIVE_THRESHOLD_MULTIPLIER = 0.8   # Normal eşiğin %80'i
