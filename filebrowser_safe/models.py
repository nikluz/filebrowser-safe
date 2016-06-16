from django.db import models

EXTENSIONS = (
    ('code', 'Code'),
    ('image', 'Image'),
    ('audio', 'Audio'),
    ('video', 'Video'),
    ('folder', 'Folder'),
    ('document', 'Document'),
)


class FileBrowserItem(models.Model):
    parent = models.ForeignKey('FileBrowserItem', null=True, blank=True)
    path = models.CharField(max_length=512)
    path_relative_directory = models.CharField(max_length=512)
    filename = models.CharField(max_length=512)
    url = models.CharField(max_length=512, null=True, blank=True)
    extension = models.CharField(max_length=64, null=True, blank=True)
    filetype = models.CharField(max_length=64, choices=EXTENSIONS,
                                null=True, blank=True)
    filesize = models.PositiveIntegerField(null=True, blank=True)
    datetime = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return self.filename
