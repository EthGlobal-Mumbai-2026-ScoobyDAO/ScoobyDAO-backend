"""Offline consistency and scope checks; this does not verify external claims."""
import json
import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parent

class CatalogChecks(unittest.TestCase):
    def test_cross_references_and_scope(self):
        catalog = json.loads((ROOT / "catalog.json").read_text(encoding="utf-8"))
        ledger = json.loads((ROOT / "claim-ledger.json").read_text(encoding="utf-8"))
        cases = catalog["cases"]
        by_id = {case["case_id"]: case for case in cases}
        self.assertEqual(len(cases), len(by_id))
        self.assertEqual(len(cases), 6)
        self.assertEqual(catalog["recommended_replay_case_id"], "bald-base-2023")
        self.assertEqual(by_id["bald-base-2023"]["chain_id"], 8453)
        self.assertEqual(by_id["anubis-ethereum-2021"]["chain_id"], 1)
        self.assertEqual(by_id["squid-bsc-2021"]["chain_id"], 56)
        self.assertEqual(by_id["meerkat-bsc-2021"]["chain_id"], 56)
        self.assertEqual(by_id["lunayield-solana-2021"]["chain"], "Solana mainnet")
        self.assertEqual(by_id["lunayield-solana-2021"]["identifier"]["kind"], "source_reported_deployer_account")
        claims = {claim["claim_id"]: claim for claim in ledger["claims"]}
        self.assertEqual(len(claims), len(ledger["claims"]))
        for case in cases:
            self.assertTrue(case["historical_only"])
            self.assertEqual(case["live_discovery_gate"], "not_evaluated")
            self.assertTrue(case["uncertainties"] and case["source_ids"] and case["claim_ids"])
            self.assertTrue(set(case["source_ids"]).issubset(catalog["sources"]))
            for claim_id in case["claim_ids"]:
                self.assertEqual(claims[claim_id]["case_id"], case["case_id"])
            address = case["identifier"]["value"]
            if case["chain_id"] is not None:
                self.assertRegex(address, r"^0x[0-9a-fA-F]{40}$")
            if case["incident_transaction"]:
                self.assertRegex(case["incident_transaction"]["hash"], r"^0x[0-9a-fA-F]{64}$")
        for claim in claims.values():
            self.assertIn(claim["case_id"], by_id)
            self.assertTrue(set(claim["source_ids"]).issubset(catalog["sources"]))
            self.assertTrue(claim["caveat"])
        for source in catalog["sources"].values():
            self.assertTrue(source["url"].startswith("https://"))

if __name__ == "__main__":
    unittest.main()
