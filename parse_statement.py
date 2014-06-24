from cStringIO import StringIO
from collections import namedtuple
import csv
import re

from pdfminer.pdfinterp import PDFResourceManager
from pdfminer.pdfinterp import PDFPageInterpreter
from pdfminer.pdfpage import PDFPage
from pdfminer.converter import TextConverter
from pdfminer.layout import LAParams

_purchase_base = namedtuple('_purchase_base',
                            ('date', 'merchant_city', 'state', 'amount',
                             'itinerary', 'foreign_amount', 'exchange_rate',
                             'exchange_date', 'foreign_currency'))


class Purchase(_purchase_base):
    def __str__(self):
        rep = '%s\t%s\t%s\t%s' % (self.date, ' '.join(self.merchant_city),
                                  self.state, self.amount)
        if self.foreign_amount:
            rep += '\t(%s %s @ %s on %s)' % (
                self.foreign_amount, self.foreign_currency,
                self.exchange_rate, self.exchange_date)
        if self.itinerary:
            padded_itin = [self.itinerary[0]]
            for line in self.itinerary[1:]:
                padded_itin.append("       %s" % line)
            rep += '\n\t%s' % '\n\t'.join(padded_itin)
        return rep


def purchases_to_csv(purchases, stream):
    order = ('date', 'merchant', 'state', 'itinerary', 'amount')
    def todict(purchase):
        return {'date': purchase.date,
                'merchant': ' '.join(purchase.merchant_city),
                'amount': purchase.amount,
                'itinerary': ('; '.join(purchase.itinerary)
                             if purchase.itinerary else ''),
                'state': purchase.state}
    writer = csv.DictWriter(stream, order)
    map(writer.writerow, map(todict, purchases))


def get_statement_text(filename):
    page2txt = []
    buf = StringIO()
    rsrcmgr = PDFResourceManager(caching=True)
    laparams = LAParams()

    laparams.char_margin = 1000

    device = TextConverter(rsrcmgr, buf, codec='utf-8', laparams=laparams,
                           imagewriter=None)
    with open(filename, 'rb') as pdff:
        interpreter = PDFPageInterpreter(rsrcmgr, device)
        for page in PDFPage.get_pages(pdff, set(),
                                      caching=True, check_extractable=True):
            interpreter.process_page(page)
            buf.seek(0)
            page2txt.append(buf.read())
            buf.truncate(0)
    return page2txt


def date_with_year(date, closing_month, closing_year):
    month, day = date.split('/')
    if month != closing_month and month == '12':
        year = str(int(closing_year) - 1)  # December
    else:
        year = closing_year
    return '/'.join((month, day, year))


def parse_purchases(page2txt):
    closing_date = (next(line for line in page2txt[0].split('\n')
                         if line.startswith('Opening/Closing Date'))
                    .strip().split()[-1])
    closing_month, closing_day, closing_year = closing_date.split('/')

    valid_regexes = map(re.compile, [
        r'^[0-9]{2}/[0-9]{2} .* -?[0-9,]*\.\d{2}',  # purchase
        r'^[0-9]{6} [0-9]',  # first leg of travel
        r'^[0-9]+ +.. [A-Z]{3}',  # continuing leg of travel,
        r'([0-9,]+\.\d{2}) X (\d+\.\d+) \(EXCHG RATE\)$',  # exchg amt/rate
        r'(\d{2}/\d{2}) +((\w+ ?)+)',  # exchange rate currency
    ])

    purchase_rx = valid_regexes[0]
    exchg_rate_rx = valid_regexes[3]
    exchg_cur_rx = valid_regexes[4]
    purchase_lines = [l.strip() for l in '\n'.join(page2txt).split('\n')
                      if any(rx.match(l.strip()) for rx in valid_regexes)]

    # If we process purchases in reverse order, then we will see all itinerary
    # legs before we see the itinerary purchase and the context sensitivity
    # will be removed
    purchase_lines = reversed(purchase_lines)
    purchases = []
    current_itinerary_reversed = []
    exchange_rate = None
    foreign_amount = None
    exchange_date = None
    foreign_currency = None

    for line in purchase_lines:
        purch_match = purchase_rx.match(line)
        cur_match = exchg_cur_rx.match(line)
        rate_match = exchg_rate_rx.match(line)

        if purch_match:
            if not current_itinerary_reversed:
                itinerary = None
            else:
                itinerary = list(reversed(current_itinerary_reversed))
            fields = line.split()
            date = date_with_year(fields[0], closing_month, closing_year)
            amount = fields[-1].replace(',','')
            state = fields[-2]
            merchant_city = fields[1:-2]
            if merchant_city[0] == '&':
                merchant_city = merchant_city[1:]
            purchases.append(
                Purchase(date, merchant_city, state, amount, itinerary,
                         foreign_amount, exchange_rate, exchange_date,
                         foreign_currency))
            current_itinerary_reversed = []
            exchange_rate = None
            foreign_amount = None
            exchange_date = None
            foreign_currency = None

        elif cur_match:
            exchange_date, foreign_currency = cur_match.groups()[:2]
        elif rate_match:
            foreign_amount, exchange_rate = rate_match.groups()[:2]
        else:
            current_itinerary_reversed.append(line)

    return list(reversed(purchases))

import sys
purchases = []
for fn in sys.argv[1:]:
    purchases.extend(parse_purchases(get_statement_text(fn)))

purchases_to_csv(purchases, sys.stdout)
