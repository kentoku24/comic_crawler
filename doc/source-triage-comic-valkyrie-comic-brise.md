# Source Triage: comic-valkyrie.com -> comic-brise.com

- Issue: `#213`
- Observed on: `2026-04-08 JST`
- Scope: public / non-login surface only
- Non-goal: adapter 実装や supported source 追加

## Decision

| Item | Decision |
| --- | --- |
| `comic-valkyrie.com` | current reading contract ではなく、legacy / discovery surface として扱う |
| `comic-brise.com` | successor ではなく、独立した current support candidate として扱う |
| `comic-valkyrie.com -> comic-brise.com` | title-level successor mapping は成立するが、host 全体を単純置換する public contract とはみなさない |
| inventory update (`#195`) | `comic-valkyrie.com` は legacy / inventory-only 側、`comic-brise.com` は current candidate 側として別建てで扱う |
| follow-up | `comic-brise.com` の独立 investigation / implementation issue は必要 |

## Public evidence

### 1. `comic-valkyrie.com` は現役トップだが、`comic-brise.com` 作品を guest / discovery 導線として混在させている

- `https://www.comic-valkyrie.com/` には `連載作品一覧` と別に `コミックブリーゼ出張掲載` セクションがある
- 同一トップ内で `コミックヴァルキリー` と `コミックブリーゼ` を並べて告知しており、`comic-brise.com` を自サイト内の current reading contract として吸収していない

Observed snippet on `2026-04-08`:

```text
<h2 class="info"><img src="img/icon_new.png" alt=""> 連載作品一覧</h2>
<h2 class="info"><img src="img/icon_brise.png" alt=""> コミックブリーゼ出張掲載</h2>
```

### 2. `comic-brise.com` は独立した current surface を持つ

- `https://www.comic-brise.com/` の title は `女性向け漫画(マンガ)読むならコミックブリーゼ` で、独立ブランドのトップとして動いている
- 同タイトル中に `無料で第1話と最新話が読めます` とあり、current reading / latest discovery contract を自ドメインで持っている

Observed snippet on `2026-04-08`:

```text
<title>コミックブリーゼ | 女性向け漫画(マンガ)読むならコミックブリーゼ。話題の悪役令嬢や、日常ほんわり系、ちょっとダークなファンタジーなどの漫画がたくさん！無料で第1話と最新話が読めます！新刊・発売日情報もたくさん！</title>
```

### 3. representative work page の latest/backnumber contract も `comic-brise.com` 側にある

- representative page: `https://www.comic-brise.com/contents/oujisamanante/`
- 同ページに `バックナンバー`、`第35話`、`第36話`、`FREE`、`TRIAL` が並んでおり、作品ページ単位の public navigation が `comic-brise.com` 側で完結している

Observed snippet on `2026-04-08`:

```text
<title>王子様なんて、こっちから願い下げですわ！～追放された元悪役令嬢、魔法の力で見返します～ | コミックブリーゼ</title>
<h2 class="common-title"><span>バックナンバー</span></h2>
<div class="number-chapter">第35話</div>
<div class="number-chapter">第36話</div>
```

## Conclusion for issue #213

- `comic-valkyrie.com` は今も public top page として生きているが、`comic-brise.com` 作品の current/latest contract を代表する host とは言い切れない
- `comic-brise.com` は独立したブランド top と作品ページ群を持つため、current support candidate として個別に扱う方が自然
- したがって `comic-valkyrie.com -> comic-brise.com` は「old/current host の単純置換」ではなく、「一部タイトルで successor mapping が必要な legacy-to-current relationship」として扱う
- `#195` の分類更新では、`comic-valkyrie.com` を current/live target として残すより、legacy / inventory-only 側へ寄せたうえで `comic-brise.com` を別 candidate として管理するのが妥当

## Follow-up recommendation

- `comic-brise.com` には独立 issue を切って、accepted input URL、canonical seed、latest/backnumber discovery の public contract を詰める
- この note 自体は evidence 固定だけに責任を持ち、supported source 追加や parser 実装は別 issue で進める
