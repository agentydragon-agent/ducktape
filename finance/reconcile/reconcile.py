"""
bazel run //finance/reconcile
"""

import datetime
import yaml
import re

from typing import Dict

from absl import app
from absl import flags
from absl import logging
import xdg

from ducktape.finance import gnucash_util
from ducktape.finance.reconcile import ubs_lib
from ducktape.finance.reconcile import splitwise_lib

#variables = globals().copy()
#variables.update(locals())
#shell = code.InteractiveConsole(variables)
#shell.interact()


def print_gnucash_split(split):
    transaction = split.parent
    print("transaction:", transaction.GetDate(), transaction.GetDescription(),
          "notes=", transaction.GetNotes())
    for s2 in transaction.GetSplitList():
        heading = "  "
        if s2.GetGUID().to_string() == split.GetGUID().to_string():
            heading = "->"

        print(heading, gnucash_util.get_split_amount(s2),
              s2.GetAccount().GetName())
        # s2.GetAccount().GetGUID().to_string()


def main(_):
    config_dir = xdg.xdg_config_home() / 'ducktape'
    cache_dir = xdg.xdg_cache_home() / 'ducktape'

    with open(config_dir / 'config.yaml', 'r') as f:
        config = yaml.safe_load(f)

    with gnucash_util.GnuCashSession(
            config['reconcile']['gnucash_book_path']) as session:
        for reconcile_config in config['reconcile']['mappings']:
            if 'gnucash_account_path' not in reconcile_config:
                raise Exception("no gnucash_account_path")

            gnucash_account_path = reconcile_config['gnucash_account_path']
            print("Reconciling", gnucash_account_path)

            account_of_interest = gnucash_util.account_from_path(
                session.book.get_root_account(), gnucash_account_path)

            if 'ubs_iban' in reconcile_config:
                # TODO: instead of using a single pointer to a single CSV, just
                # load the latest one. Make sure it is for the right IBAN.
                external_transaction_by_external_id = ubs_lib.load_ubs_csv(
                    reconcile_config['csv_path'])
                id_regex = r"ubs_transaction_id=([0-9A-Z]+)"
                pass
            elif 'splitwise_group_id' in reconcile_config:
                id_regex = r"splitwise=([0-9]+)"
                external_transaction_by_external_id = splitwise_lib.load_splitwise_expenses(
                    reconcile_config['splitwise_group_id'])
                pass
            else:
                raise Exception(f"no way to reconcile: {reconcile_config}")

            # 'start_date' sets date at which mapping starts
            if 'start_date' in reconcile_config:
                start_date = datetime.datetime.strptime(
                    reconcile_config['start_date'], '%Y-%m-%d').date()

                external_transaction_by_external_id = {
                    external_id: external_transaction
                    for external_id, external_transaction in
                    external_transaction_by_external_id.items()
                    if external_transaction.trade_date >= start_date
                }

            # External IDs that have been matched.
            matched_external_ids = set()
            gnucash_unmatched_splits = []

            errors = 0
            for split in account_of_interest.GetSplitList():
                memo = split.GetMemo()
                match = re.search(id_regex, memo)

                if match:
                    external_id = match.group(1)
                    transaction = external_transaction_by_external_id[
                        external_id]

                    split_amount = gnucash_util.get_split_amount(split)
                    if split_amount != transaction.amount:
                        logging.error(
                            f"Error with transaction {external_id}: split in GnuCash is {split_amount}, but external system says {transaction.amount}"
                        )
                        errors += 1
                    assert external_id not in matched_external_ids, f"{external_id} matched to 2 transactions in GnuCash"
                    matched_external_ids.add(external_id)
                    continue

                # transaction is not matched
                gnucash_unmatched_splits.append(split)

                #print("split:", split)
                # split.GetAccount().GetName()
                # >>> t.GetCurrency().get_fullname() --> 'Swiss Franc'

            if errors > 0:
                raise Exception(f"{errors} errors")

            unmatched_ids = set(external_transaction_by_external_id.keys()
                                ) - matched_external_ids
            print()
            print("Unmatched in external system:")

            # Sort by descending net
            def get_abs_net(expense_id):
                return abs(
                    external_transaction_by_external_id[expense_id].amount)

            for expense_id in sorted(unmatched_ids,
                                     key=get_abs_net,
                                     reverse=True):
                print(external_transaction_by_external_id[expense_id])
            print()
            print("Unmatched in GnuCash:")

            # Sort by descending net
            def get_abs_split_net(split):
                return abs(gnucash_util.get_split_amount(split))

            for split in sorted(gnucash_unmatched_splits,
                                key=get_abs_split_net,
                                reverse=True):
                print_gnucash_split(split)


if __name__ == '__main__':
    app.run(main)
