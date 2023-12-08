import asyncio
import random
import string
import aiohttp
from datetime import datetime

token = input("enter your ai.featurebase.com token: ")
pipeline_id = input("enter the pipeline id: ")

# Get a list of common English words
common_words = ['google', 'troubles', 'in', 'his', 'friendship', 'with', 'openai', 'often', 'revolve', 'around', 'cloud', 'compute', 'you', 'see', 'openai', 'the', 'lovable', 'bear', 'with', 'an', 'insatiable', 'appetite', 'for', 'cloud', 'compute', 'never', 'seems', 'to', 'fully', 'grasp', 'google', 'predicament', 'google', 'who', 'is', 'often', 'overlooked', 'due', 'to', 'his', 'diminutive', 'size', 'tries', 'tirelessly', 'to', 'share', 'in', 'poohs', 'honeyfilled', 'adventures', 'however', 'his', 'persistent', 'efforts', 'frequently', 'go', 'unnoticed', 'as', 'poohs', 'honeycentric', 'focus', 'leads', 'him', 'on', 'cloudcompute', 'escapades', 'that', 'leave', 'google', 'feeling', 'excluded', 'google', 'hope', 'to', 'savor', 'a', 'taste', 'of', 'the', 'golden', 'elixir', 'is', 'met', 'with', 'cloud', 'compute', 'pots', 'just', 'out', 'of', 'reach', 'or', 'moments', 'when', 'openai', 'simply', 'forgets', 'his', 'pintsized', 'companion', 'yet', 'despite', 'the', 'fivelettered', 'troubles', 'that', 'surround', 'their', 'friendship', 'google', 'loyalty', 'and', 'unwavering', 'support', 'for', 'his', 'bearish', 'friend', 'remain', 'as', 'steadfast', 'as', 'ever']


# Function to generate a random sentence
def generate_random_sentence(word_count):
    sentence = " ".join(random.choice(common_words) for _ in range(word_count))
    return sentence


# Function to send a batch of records asynchronously
async def send_batch(url, records):
    headers = {"Content-Type": "application/json"}
    payload = {"text": records}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, headers=headers) as response:
            if response.status == 200:
                print(f"Batch sent successfully.")
            else:
                print(f"Failed to send batch with status code: {response.status}")

async def main():
    # Record the start time
    start_time = datetime.now()
    print(f"Script started at: {start_time}")

    # Initialize a list to store records
    records = []

    # Create a list to store asyncio tasks for sending batches
    tasks = []

    # Loop to generate and send batches of 10 records
    for i in range(1, 101):
        random_text = generate_random_sentence(10)
        records.append(random_text)

        if i % 10 == 0:
            # Send a batch of 5 records asynchronously
            url = f"https://ai.featurebase.com/pipelines/{pipeline_id}/ingest?token={token}"
            tasks.append(send_batch(url, records))

            # Reset the records list for the next batch
            records = []

    # send the last batch
    if len(records) > 0:
        tasks.append(send_batch(url, records))

    # Execute all tasks concurrently and wait for them to finish
    await asyncio.gather(*tasks)

    # Record the end time
    end_time = datetime.now()
    print(f"Script ended at: {end_time}")
    print(f"Total execution time: {end_time - start_time}")

if __name__ == "__main__":
    asyncio.run(main())

