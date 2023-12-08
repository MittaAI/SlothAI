# SlothAI: A Model Pipeline Manager
SlothAI is an Open Source system designed for asynchronous AI inferences, with a user-friendly interface for editing templates that manage pipeline flows. It utilizes containers and task queues for data processing tasks.

SlothAI is designed for speed.

<img src="https://raw.githubusercontent.com/kordless/SlothAI/SlothAI/SlothAI/static/images/sloth.png?raw=true" width="240"/>

In SlothAI, pipelines are built with templates and nodes that transform data fields sent to the pipeline. These nodes supports deserialization of calls to AI models, which greatly increase the speed of indexing and querying large amounts of data.

You can try out SlothAI at [MittaAI](https://mitta.ai/). SlothAI uses [FeatureBase Cloud](https://cloud.featurebase.com/) for storage.

Machine learning box deployment is managed using [Laminoid](https://github.com/FeatureBaseDB/Laminoid).

## But, Why?
Individual movements of a sloth are measured and intentional, mirroring the pace of synchronous ETL processes when seen alone. SlothAI's true capability, akin to the combined might of a sloth hoard, becomes apparent when it functions asynchronously, parallelizing inference steps to increase the speed of data transformations.

SlothAI distinguishes itself from other frameworks like LangChain, AutoChain, Auto-GPT, and Ray by focusing on scalable asynchronous inferences coupled with an intuitive UI that simplifies the editing of templates and the management of pipeline flows. SlothAI makes template editing and debugging fun and easy.

SlothAI use a SQL engine (FeatureBase) capable of point lookups, binary set operations, and vector similarity for its storage layers. Tasks are executed within containers on Google Cloud via task queues, and for more demanding inferencing tasks, it orchestrates calls to GPU boxes, streamlining the process of running large model inferences.

In the world of data, async ETL's strength is not in the speed of a single process, but in the collective and orchestrated efforts that move mountains of data with remarkable agility.

## Template Strategy
Templates are at the core of SlothAI's design. There's no need to dig through directories or code lines to find the right template. In SlothAI, templates are easily accessible the UI and central to building powerful pipelines.

SlothAI provides a wide selection of basic templates for interfacing with various types of models, enabling nodes to crawl the web, read documents, listen to audio files, extract objects from images, generate images, embed text for searching, store data, and more. Templates are built using Jinja2, which enables running code within the template itself as data is being processed, ensuring a smooth and integrated workflow.

Templates are the essence of SlothAI's strategy for effective communication with large language models. Templates may transform prompts to LLMs, format data for embeddings, and be used to create custom SQL queries for data retrieval.

## Storage Opinions
SlothAI is opinionated, inasmuch that it uses FeatureBase for its SQL processing to handle tabular data retrieval, set operations with a binary tree storage, and vector comparisons with a tuple storage layer. These features, together in one storage layer, are necessary to deliver datasets to machine learning models for prompt augmentation and training data management.

Other storage backends will be added to the system in the future.

## Pipelines
SlothAI allows for building powerful ingest pipelines comprising nodes that serve as ETL (Extract, Transform, Load) functions, altering and enriching data fields as they pass through. Each node is capable of executing a transformation, extending one field into multiple fields. 

These nodes are arranged to process machine learning model workloads in sequence during data ingestion. The pipelines facilitate rapid ETL by enabling de-serialization by splitting task operations on data.

Query pipelines extend this concept, where data enters through POST requests and exits transformed datasets ready for loading, whether into databases or forwarded to the user via callbacks. Pipelines can be easily integrated with other services or automation tools.

### Sample Ingestion Graph
The following graph outlines a typical RAG-based *ingestion pipeline* for data which extracts keyterms, embeds the text and keyterms together, then forms a question about the text and keyterms using GPT-3.5-turbo. The results are saved into FeatureBase for query interactions:

<img src="https://github.com/kordless/SlothAI/blob/SlothAI/SlothAI/static/images/pipeline_graph.png" width="360"/>

## Development Notes
* Processor support for reading text or PDFs, audio files, image files, or use of custom data models.
* Embeddings and generative completion processing is supported.
* Vector search is supported and vector balancing is provided using set operations.
* Templates and pipelines may be exported for version control or sharing.
* Powerfully simple UI provides pipeline creation and debugging in one view.
* Set storage layer for PostgreSQL/pgvector is in the works.

## Authentication
Authentication is done via email and tokens using Twilio. Instructions for setup is coming soon.

Security to the Laminoid controller is done through box tokens assigned to network tags in Google Compute. This secures the deployment somewhat, but could be better.

This project could be run in a VPC-like setup and use private models. We'll need to do work to get it there.

## Configuration
Create a `config.py` configuration file in the root directory. Use `config.py.example` to populate.

Keys, tokens and IPs are created as needed.

### Dependencies - MacOS
You will need Xcode installed first before the requirements can be installed with `pip`. To do this on most versions of MacOS do the following:

```
xcode-select --install
```

Once the install has finished, you'll need to accept the license:

```
sudo xcodebuild -license
```

### Dependencies - Conda
Install conda and activate a new environment:

```
conda create -n slothai python=3.9
conda activate slothai
```

Install the requirements:

```
pip3 install -r requirements
```

### Dependencies - FeatureBase
You will need a FeatureBase cloud account to use the read_fb and write_fb processors. It's free to signup and requires your email address: https://cloud.featurebase.com/.

### Dependencies - Google Cloud
You'll need a whole bunch of Google Cloud things done. Enabling AppEngine, Compute, Cloud Tasks, domain names, firewalls and setting up credentials will eventually be documented here.

## Install

To deploy to your own AppEngine:

```
./scripts/deploy.sh --production
```

Deploy the cron.yaml after updating the key (use the `cron.yaml.example` file):

```
gcloud app deploy cron.yaml
```

Create an AppEngine task queue (from the name in `config.py`):

```
gcloud tasks queues create sloth-spittle --location=us-central1 
```

Create a storage bucket for user files:

```
gsutil mb gs://[BUCKET_NAME]
```

To deploy for local development:

```
./scripts/dev.sh
```

## Testing

To run tests run the following from the root directory:

```
pytest
```

To get test coverage run:
```
pytest --cov=SlothAI --cov-report=html
```

## Use
Login to the system using your custom domain name, or the *appspot* URL, which you can find in the Google Cloud console.

For local development, use the following URL:

```
http://localhost:8080
```

### Login
To login to the system, use your FeatureBase Cloud [database ID](https://cloud.featurebase.com/databases) and [API key](https://cloud.featurebase.com/configuration/api-keys) (token).
