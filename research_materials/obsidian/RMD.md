---
exampleProperty: ""
fundamentals:
  - ROA > 8%
  - ROE > 12% ⚠️
  - ROI > 8%
  - Net Profit Margin > 0% ⚠️
  - EPS Growth Past 5 Yrs > 0%
  - EPS Growth Past Yr > 0%
  - EPS Growth Next Yr > 0%
  - Sales Growth Past 5 Yrs > 0%
  - Current Ratio > 1
  - Debt to Equity < 0.4
action: NO ACTION
MOS: []
company: ResMed
companySize:
  - Market Cap >$1B
SM:
  - Top 3 SM Increasing Stake
liquidity:
  - Avg Daily Liquidity + Volume > 10X Position Expected
notes: Overvalued.
---
#The_Freedom_Trader 

# Stock Buying Checklist

> [!SETTINGS] **Entity Details** 
>**Analysis Date:** `INPUT[datePicker:date]`
> **Company Name:** `INPUT[text:company]`

---

> [!ABSTRACT] Fundamental Stock Assessment > 7/10
> `VIEW[{fundamentals}.length]` / 10 criteria met
```meta-bind
INPUT[multiSelect(option(ROA > 8%), option(ROE > 12% ⚠️), option(ROI > 8%), option(Net Profit Margin > 0% ⚠️), option(EPS Growth Past 5 Yrs > 0%), option(EPS Growth Past Yr > 0%), option(EPS Growth Next Yr > 0%), option(Sales Growth Past 5 Yrs > 0%), option(Current Ratio > 1), option(Debt to Equity < 0.4)):fundamentals]
```

> [!NOTE] Company Size
```meta-bind
INPUT[multiSelect(option(Market Cap >$1B)):companySize]
```

> [!IMPORTANT] Smart Money Involvement
```meta-bind
INPUT[multiSelect(option(SM Holding > 5% ⚠️), option(Top 3 SM Increasing Stake)):SM]
```

> [!NOTE] Liquidity & Volume Assessment
```meta-bind
INPUT[multiSelect(option(Avg Daily Liquidity + Volume > 10X Position Expected)):liquidity]
```


> [!EXAMPLE] INVESTMENT - Valuation Spreadsheet
```meta-bind
INPUT[multiSelect(option(Price < MOS ⚠️)):MOS]
```
```meta-bind-button
label: Valuation
icon: ""
style: primary
class: ""
cssStyle: "display: block; width: fit-content; margin: 0 auto;"
backgroundImage: ""
tooltip: ""
id: ""
hidden: false
actions:
  - type: open
    link: Assets/theFreedomTrader_Equity_Multiple_Valuation_Calculator_v2.0.xlsm
    newTab: false
```

---

> [!SUCCESS] Technical Assessment
>
> | | 🔵 Trade | 🟢 Investment |
> |--|----------|---------------|
> | **RSI** ⚠️| < 35 & UP | < 40 & UP |
> | **STO Slow** ⚠️| < 20 | < 20 |
> | **STO Cross** ⚠️| Fast over Slow | Fast over Slow |

---

### 📝 Analyst Notes
> [!EDIT] Notes
> ACTION: `INPUT[inlineSelect(option(INVESTMENT), option(TRADE), option(NO ACTION)):action]`
> 
> `INPUT[textArea:notes]`

