# Reviewing a purchase order

For the person at the order desk. No technical knowledge needed.

## Where to start

**Orderkoll → Documents** opens on the **To do** filter: everything that needs a look,
is ready to become a quotation, or failed. Yellow rows need you; green rows are ready.

## The review screen

- **Left:** the purchase order as the customer sent it (PDF, or the email text / sheet).
- **Right:** customer, PO number, totals, and the order lines Orderkoll read.
- **Top, yellow box:** a short list of what still has to be done, in plain words.
  When it is empty the document turns **Ready** by itself.

Line colours: **green** = product found and price OK, **yellow** = Orderkoll does not know
which product this is, **red** = the price differs from this customer's pricelist.

## Fixing what stopped it

| The yellow box says | What you do |
|---|---|
| Pick the customer | Click **Pick customer**, choose the company. Tick "remember" so the next mail from this sender is recognised. |
| Map N line(s) to a product | Click **Map** on each yellow line, choose the product. With "Remember for this customer" ticked, the same code is recognised next time. |
| Price(s) differ from the pricelist | Correct the price on the line, or click **Accept price** (✓) if the customer's price is right for this order. The pricelist itself is not changed. |
| The lines add up to X but the PO says Y | Correct the line that was read wrong (quantity or price), or the **Printed amount** if that was misread. |
| This PO number was already received | Usually **Reject** it. If it really is a new order, click **Not a duplicate**. |
| Scanned PDF read by OCR | Compare quantities and prices with the PDF, fix any line, then click **Mark scan as checked**. |

Every change re-runs all checks at once and writes a short summary in the history
(chatter) at the bottom right, so there is a record of who changed what.

## Rejecting

Click **Reject** and type the reason (required). The reason is kept on the document and
in its history.

## Re-run extraction

**Re-run extraction** reads the file again and replaces the lines, including your edits.
Use it only if the lines were read badly from the start.
