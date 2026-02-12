# asterisk-lang
Lark製の最小スクリプト言語です。変数と組み込み関数が使えます。

## 使い方
```bash
pip install -r requirements.txt
python mini_lang.py
```

## 文法(短縮)
- 代入: `x = 1 + 2`
- 出力: `print(x)`
- 関数: `len("abc")`, `upper("abc")`, `lower("ABC")`, `str(1)`, `int("2")`

## エラー表示
- 未定義変数/関数: 名前を表示
- 構文エラー: 行・列と期待トークンを表示
