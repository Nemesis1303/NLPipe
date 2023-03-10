import json
import argparse
from src.pipe import Pipe
from src.utils import det
import logging
from dask.diagnostics import ProgressBar
import pathlib
import dask.dataframe as dd
import pandas as pd
import time

# ########################
# Main body of application


def main():

    # Read input arguments
    parser = argparse.ArgumentParser(
        description="NLPipe")
    parser.add_argument("--source_path", type=str, default=None,
                        required=True, help="Path to the source file")
    parser.add_argument("--source_type", type=str, default='parquet',
                        required=False, help="Source file's format")
    parser.add_argument("--source", type=str, default=None,
                        required=True, help="Name of the dataset to be preprocessed (e.g., cordis, scholar, etc.)")
    parser.add_argument("--destination_path", type=str, default=None,
                        required=True, help="Path to save the preprocessed data")
    parser.add_argument("--stw_path", type=str, default="data/stw_lists",
                        required=False, help="Folder path for stopwords")
    parser.add_argument("--nw", type=int, default=0,
                        required=False, help="Number of workers to use with Dask")

    # Create logger object
    logging.basicConfig(level='INFO')
    logger = logging.getLogger('nlpPipeline')

    args = parser.parse_args()
    source_path = pathlib.Path(args.source_path)
    destination_path = pathlib.Path(args.destination_path)

    # Get stopword lists
    stw_lsts = []
    for entry in pathlib.Path(args.stw_path).iterdir():
        # check if it is a file
        if entry.as_posix().endswith("txt"):
            stw_lsts.append(entry)

    # Create pipeline
    nlpPipeline = Pipe(stw_files=stw_lsts, logger=logger)

    # Read config file to get the id, title and abstract fields associated with the dataset under preprocessing
    with open('config.json') as f:
        field_mappings = json.load(f)

    if args.source in field_mappings:
        mapping = field_mappings[args.source]
        logger.info(f"Reading from {args.source}...")
        id_fld = mapping["id"]
        raw_text_fld = mapping["raw_text"]
        title_fld = mapping["title"]
    else:
        logger.error(f"Unknown source: {args.source}")

    readers = {
        "xlsx": lambda path: dd.from_pandas(pd.read_excel(path), npartitions=3).fillna(""),
        "parquet": lambda path: dd.read_parquet(path).fillna("")
    }

    # Get reader according to file format
    if args.source_type in readers:
        reader = readers[args.source_type]
        df = reader(source_path)
    else:
        logger.error(f"Unsupported source type: {args.source_type}")

    # Keep only necessary columns
    corpus_df = df[[id_fld, raw_text_fld, title_fld]]

    # Detect abstracts' language and filter out those non-English ones
    corpus_df = \
        corpus_df[corpus_df[raw_text_fld].apply(
            det,
            meta=('langue', 'object')) == 'en']

    # Concatenate title + abstract/summary
    corpus_df["raw_text"] = \
        corpus_df[[title_fld, raw_text_fld]].apply(
            " ".join, axis=1, meta=('raw_text', 'object'))
    # Filter out rows with no raw_text
    corpus_df = corpus_df.dropna(subset=["raw_text"], how="any")

    logger.info(f'-- -- NLP preprocessing starts...')

    start_time = time.time()
    corpus_df = nlpPipeline.preproc(corpus_df)
    logger.info(
        f'-- -- NLP preprocessing finished in {(time.time() - start_time)}')

    # Save new df in parquet file
    outFile = destination_path.joinpath("preproc_" + args.source + ".parquet")
    if outFile.is_file():
        outFile.unlink()

    with ProgressBar():
        if args.nw > 0:
            corpus_df.to_parquet(outFile, write_index=False, schema="infer", compute_kwargs={
                'scheduler': 'processes', 'num_workers': args.nw})
        else:
            # Use Dask default number of workers (i.e., number of cores)
            corpus_df.to_parquet(outFile, write_index=False, schema="infer", compute_kwargs={
                'scheduler': 'processes'})

    return


# ############
# Execute main
if __name__ == '__main__':
    main()
