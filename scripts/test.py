from SlothAI.web.custom_commands import chunk_with_page_filename
texts = [
    "The cool, calm night descended as the cats gathered in their secret party location. Under the shimmering moonlight, they donned tiny party hats and danced to the rhythm of the catnip beat. The feline DJ spun tracks that echoed through the alley, creating an atmosphere of pure feline euphoria. Cat cocktails flowed freely, and the kitties meowed in harmony, celebrating the wildest cat party of the year.",
    "It was a purrfectly wild night as the cats unleashed their inner party animals. The DJ cat blasted electrifying beats that had even the laziest of cats on their feet. Disco lights bounced off their glossy fur, creating a dazzling spectacle. Kitten cocktails were served in fishbowl glasses, and the dance floor was a sea of twirling tails. The party went on until the break of dawn, leaving no doubt that cats know how to paw-ty!",
    "The feline fiesta was in full swing, with cats from all walks of life coming together to celebrate. The tabbies and the Siamese, the Persians and the Maine Coons, all grooved to the cat rock band's tunes. The party was a whirlwind of fur, glitter, and sparkles, with acrobatic cats performing daring feats. Catnip confetti filled the air, and laughter echoed in every corner as the cats painted the town red.",
    "The grand cat soirée had cats in top hats, tails, and tuxedos. They danced the night away, swinging from chandeliers and scratching turntables. The night was filled with meow-mazing performances, from breakdancing kittens to opera-singing tabbies. The party was truly the cat's pajamas, and they partied until the sun peeked over the horizon, signaling the end of the most epic cat bash ever."
]

filename = "example.txt"
overlap = 1

chunks = chunk_with_page_filename(texts, filename, length=512, overlap=1)
print(chunks)
