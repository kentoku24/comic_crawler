# Prompt Examples

必要なときだけこのファイルを読む。
この skill は workflow を内包しているので、呼び出し文面は Issue 指定だけで十分。

## 1. 基本形

```text
Use $gh-issue-maker-chief-engineer-loop on this issue:
<owner/repo#number or issue URL>
```

## 2. 日本語の基本形

```text
$gh-issue-maker-chief-engineer-loop を使ってこの Issue を進めてください。

対象 Issue:
<owner/repo#number or issue URL>
```

## 3. PR 作成まで明示したい場合だけ足す形

```text
$gh-issue-maker-chief-engineer-loop を使ってこの Issue を進めてください。

対象 Issue:
<owner/repo#number or issue URL>

親セッションで統合して PR を作成または更新しながら進めてください。
```
